"""Append-only audit log (planning.md sections 6 and 8).

Every attribution decision and every appeal lands here as one JSON object on
one line. Two properties the rest of the system depends on:

- **Append-only.** Nothing rewrites an entry. An appeal does not edit the
  decision it contests; it appends a second entry pointing back at the first.
  That is what makes the log usable as evidence when a creator disputes a
  result.
- **Hash, not text.** Section 4 splits retention deliberately. The content
  store keeps the full text because an appeal reviewer has to read it. The log
  keeps only a hash, so the audit trail does not become a second copy of every
  creator's work.
"""

import json
import os
import threading
import uuid
from datetime import datetime, timezone

import config


def _now_ms():
    """ISO 8601 UTC with millisecond precision."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class AuditLog:
    def __init__(self, path=None):
        self.path = path or config.AUDIT_LOG_PATH
        self._lock = threading.Lock()

    # --- writing ----------------------------------------------------------

    def _append(self, entry):
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return entry

    def append_decision(
        self,
        record,
        signals,
        ai_likelihood,
        attribution,
        confidence=None,
        label_variant=None,
        latency_ms=None,
        confidence_components=None,
        rules_fired=None,
    ):
        """Record one attribution decision.

        The flat per-signal scores duplicate what is already in `signals`.
        That is safe here in a way it would not be in a mutable store: entries
        are written once and never updated, so the copies cannot drift apart.
        The flat fields exist so the log can be read with grep and jq without
        indexing into an array.
        """
        by_name = {s["name"]: s for s in signals}
        entry = {
            "event": "decision",
            "entry_id": str(uuid.uuid4()),
            "timestamp": _now_ms(),
            "content_id": record["content_id"],
            "creator_id": record.get("creator_id"),
            "status": record["status"],
            "attribution": attribution,
            "ai_likelihood": ai_likelihood,
            "confidence": confidence,
            "confidence_components": confidence_components,
            "rules_fired": rules_fired or [],
            "stylometric_score": (by_name.get("stylometric") or {}).get("score"),
            "llm_score": (by_name.get("llm_judge") or {}).get("score"),
            "signals": signals,
            "text_hash": record["text_hash"],
            "text_length": record["text_length"],
            "content_type": record.get("content_type"),
            "label_variant": label_variant,
            "ruleset_version": config.RULESET_VERSION,
            "judge_model": config.JUDGE_MODEL if "llm_judge" in by_name else None,
            "latency_ms": latency_ms,
        }
        return self._append(entry)

    def append_appeal(
        self, content_id, appeal_id, creator_id, reasoning, grounds,
        contested_entry_id, new_status="under_review",
    ):
        """Record a creator's challenge, linked to the decision it contests.

        Implemented now rather than in M5 so the link field is fixed before
        anything depends on it.
        """
        entry = {
            "event": "appeal",
            "entry_id": str(uuid.uuid4()),
            "timestamp": _now_ms(),
            "content_id": content_id,
            "appeal_id": appeal_id,
            "creator_id": creator_id,
            "appeal_reasoning": reasoning,
            "grounds": grounds,
            "status": new_status,
            "contested_decision_entry_id": contested_entry_id,
            "new_status": new_status,
        }
        return self._append(entry)

    # --- reading ----------------------------------------------------------

    def read(self, limit=None, offset=0, content_id=None, event=None, order="desc"):
        """Return a page of entries, most recent first by default.

        The window is taken from the END of the log. Slicing from the start
        meant that once the log grew past one page, recent activity became
        invisible: the first 50 entries ever written came back forever. For a
        log endpoint that is the wrong default.

        order="asc" returns the same window oldest-first, which is how a
        decision and the appeal contesting it read as a chain.
        """
        limit = min(limit or config.AUDIT_LOG_DEFAULT_LIMIT, config.AUDIT_LOG_MAX_LIMIT)
        entries = []
        with self._lock:
            if not os.path.exists(self.path):
                return [], 0
            with open(self.path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        # A truncated final line from an interrupted write must
                        # not make the whole log unreadable.
                        continue
                    if content_id and entry.get("content_id") != content_id:
                        continue
                    if event and entry.get("event") != event:
                        continue
                    entries.append(entry)
        total = len(entries)

        # Page backwards from the newest entry.
        newest_first = list(reversed(entries))
        window = newest_first[offset:offset + limit]
        if order == "asc":
            window = list(reversed(window))
        return window, total

    def latest_decision_entry_id(self, content_id):
        """The entry an appeal on this content would contest."""
        entries, _ = self.read(limit=config.AUDIT_LOG_MAX_LIMIT,
                               content_id=content_id, event="decision")
        # read() is newest-first, so the most recent decision is entries[0].
        return entries[0]["entry_id"] if entries else None

    def count(self):
        _, total = self.read(limit=config.AUDIT_LOG_MAX_LIMIT)
        return total


def redact_for_public(entry):
    """Strip creator text fragments from an entry bound for `GET /log`.

    The judge cites verbatim phrases from the submission, which a reviewer
    needs and an anonymous reader does not. The entry on disk keeps them. This
    removes them from the HTTP response, which is unauthenticated in this
    build. Scores, categories, and every number stay, so nothing needed to
    audit a decision is lost.
    """
    import copy

    public = copy.deepcopy(entry)
    for signal in public.get("signals") or []:
        if signal.get("evidence"):
            signal["evidence_count"] = len(signal["evidence"])
            signal["evidence"] = "[redacted: quotes creator text]"
        if signal.get("name") == "llm_judge" and signal.get("reasons"):
            # Judge reasons embed the same quotes.
            signal["reasons"] = [
                r.split(":", 1)[0] + ": [redacted]" if ': "' in r else r
                for r in signal["reasons"]
            ]
    # Appeal reasoning is NOT redacted, unlike judge evidence quotes. The two
    # are different in kind. A judge quote is a fragment of the creator's
    # creative work, lifted without their involvement. Appeal reasoning is a
    # statement the creator wrote deliberately, for this process, to be read.
    #
    # It can still carry personal detail, and the sample appeal in the brief
    # discloses that the writer is a non-native English speaker. Section 6
    # records that this endpoint needs authentication in production for
    # exactly that reason.
    return public
