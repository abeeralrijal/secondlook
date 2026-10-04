"""In-memory content store.

Retains full submission text. planning.md section 4 splits retention: the audit
log stores a hash so it does not duplicate creator content, and this store keeps
the text because an appeal reviewer cannot evaluate a case without reading it.
"""

import hashlib
import threading
import uuid
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


class ContentStore:
    def __init__(self):
        self._items = {}
        self._lock = threading.Lock()

    def create(self, text, creator_id=None, content_type="other"):
        content_id = str(uuid.uuid4())
        record = {
            "content_id": content_id,
            "text": text,
            "text_hash": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "text_length": len(text),
            "creator_id": creator_id,
            "content_type": content_type,
            "status": "pending",
            "received_at": _now(),
            "verdict": None,
            "ai_likelihood": None,
            "confidence": None,
            "analyzed_at": None,
        }
        with self._lock:
            self._items[content_id] = record
        return record

    def record_analysis(self, content_id, ai_likelihood, verdict=None, confidence=None):
        with self._lock:
            record = self._items[content_id]
            record["ai_likelihood"] = ai_likelihood
            record["verdict"] = verdict
            record["confidence"] = confidence
            record["status"] = "classified"
            record["analyzed_at"] = _now()
            return record

    def set_status(self, content_id, status):
        with self._lock:
            record = self._items[content_id]
            record["status"] = status
            return record

    def get(self, content_id):
        with self._lock:
            return self._items.get(content_id)

    def count(self):
        with self._lock:
            return len(self._items)
