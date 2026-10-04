"""ProvenanceGuard API. Milestone 3: submission endpoint and signal 1.

Not yet implemented, per planning.md section 11: the LLM judge, fusion and
confidence scoring, label generation, appeals, and the audit log. Response
fields that depend on those milestones are returned as null rather than
omitted, so the shape stays stable against the section 6 contract.
"""

import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from flask_limiter import Limiter

import config
from appeals import GROUNDS, AppealStore
from audit import AuditLog, redact_for_public
from errors import ApiError, register_error_handlers
from fusion import fuse
from labels import generate_label
from signals.judge import judge_signal
from signals.stylometric import stylometric_signal
from store import ContentStore
from validation import validate_submission


def _rate_limit_key():
    """Bucket by API key when supplied, by client address otherwise."""
    return request.headers.get("X-API-Key") or (request.remote_addr or "anonymous")


def _public_signal(signal):
    """Strip sub-metric internals from the API response.

    components carries raw statistics and is written to the audit log in M5.
    The creator sees scores and plain-language reasons.
    """
    return {
        "name": signal["name"],
        "score": signal["score"],
        "weight": signal["weight"],
        "status": signal["status"],
        "reasons": signal["reasons"],
    }


def create_app(store=None, audit_log=None, judge=None, appeal_store=None):
    app = Flask(__name__)
    app.config["RATELIMIT_HEADERS_ENABLED"] = config.RATELIMIT_HEADERS_ENABLED
    app.config["content_store"] = store or ContentStore()
    app.config["audit_log"] = audit_log or AuditLog()
    # Injectable so tests can exercise fusion without spending tokens.
    app.config["judge"] = judge or judge_signal
    app.config["appeal_store"] = appeal_store or AppealStore()

    limiter = Limiter(
        key_func=_rate_limit_key,
        app=app,
        default_limits=[],
        storage_uri=config.RATELIMIT_STORAGE_URI,
    )
    register_error_handlers(app)

    @app.errorhandler(429)
    def _handle_rate_limit(exc):
        response, status = ApiError(
            429,
            "RATE_LIMITED",
            "Too many requests. Try again shortly.",
            detail={"limit": str(getattr(exc, "description", ""))},
        ).to_response()
        # The extension also sets this via an after_request hook when
        # RATELIMIT_HEADERS_ENABLED is on. Set it here too so the contract
        # does not depend on that hook surviving a config change.
        retry_after = getattr(exc, "retry_after", None)
        if retry_after:
            response.headers["Retry-After"] = str(int(retry_after))
        return response, status

    @app.post("/submit")
    @limiter.limit(config.SUBMIT_RATE_LIMITS)
    def submit():
        payload = request.get_json(silent=True)
        if payload is None:
            raise ApiError(400, "INVALID_TYPE", "Request body must be valid JSON.")

        submission = validate_submission(payload)
        content_store = app.config["content_store"]
        record = content_store.create(
            submission["text"], submission["creator_id"], submission["content_type"]
        )

        started = datetime.now(timezone.utc)
        stylometric = stylometric_signal(submission["text"])
        judge_result = app.config["judge"](submission["text"])
        latency_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

        signals = [stylometric, judge_result]
        result = fuse(stylometric, judge_result, len(submission["text"]))

        ai_likelihood = result["ai_likelihood"]
        attribution = {
            "result": result["verdict"],
            "basis": "both_signals" if all(s["status"] == "ok" for s in signals)
                     else "no_signal_scored" if not any(s["status"] == "ok" for s in signals)
                     else "degraded_single_signal",
            "is_final": True,
        }
        updated = content_store.record_analysis(
            record["content_id"], ai_likelihood,
            verdict=result["verdict"], confidence=result["confidence"],
        )
        label = generate_label(result["verdict"], result["confidence"],
                               updated["status"])

        # Written before the response is built. A decision the caller was told
        # about but that never reached the log would be unauditable, and the
        # log is the only record an appeal reviewer gets.
        app.config["audit_log"].append_decision(
            record=updated,
            signals=signals,
            ai_likelihood=ai_likelihood,
            attribution=result["verdict"],
            confidence=result["confidence"],
            label_variant=label["variant"],
            latency_ms=latency_ms,
            confidence_components=result["components"],
            rules_fired=result["rules_fired"],
        )

        return jsonify(
            {
                "content_id": record["content_id"],
                "status": "classified",
                "attribution": attribution,
                "ai_likelihood": ai_likelihood,
                "confidence": result["confidence"],
                "confidence_components": result["components"],
                "rules_fired": result["rules_fired"],
                "label": label,
                "signals": [_public_signal(s) for s in signals],
                "analyzed_at": content_store.get(record["content_id"])["analyzed_at"],
                "ruleset_version": config.RULESET_VERSION,
                "latency_ms": latency_ms,
            }
        ), 200

    @app.post("/appeal")
    @app.post("/appeal/<content_id>")
    @limiter.limit(config.APPEAL_RATE_LIMITS)
    def appeal(content_id=None):
        """File a creator's contest of a classification.

        `content_id` may arrive in the path or the body. The body form is the
        documented contract; the path form predates it and still works so
        existing callers do not break.

        The reasoning field is accepted as `creator_reasoning`, with
        `reasoning` kept as an alias for the same reason.
        """
        payload = request.get_json(silent=True)
        if payload is None or not isinstance(payload, dict):
            raise ApiError(400, "INVALID_TYPE", "Request body must be a JSON object.")

        content_id = content_id or payload.get("content_id")
        if not isinstance(content_id, str) or not content_id.strip():
            raise ApiError(
                400, "MISSING_FIELD",
                "'content_id' is required in the path or the body.",
                field="content_id",
            )
        content_id = content_id.strip()

        content_store = app.config["content_store"]
        record = content_store.get(content_id)
        if record is None:
            raise ApiError(404, "CONTENT_NOT_FOUND", "No such content id.")

        appeal_store = app.config["appeal_store"]
        if appeal_store.exists_for(content_id):
            raise ApiError(
                409, "ALREADY_APPEALED",
                "An appeal is already on file for this content.",
            )

        reasoning = payload.get("creator_reasoning")
        if reasoning is None:
            reasoning = payload.get("reasoning")
        if not isinstance(reasoning, str) or not reasoning.strip():
            raise ApiError(
                400, "MISSING_FIELD", "'reasoning' is required.", field="reasoning"
            )
        reasoning = reasoning.strip()
        if len(reasoning) < config.MIN_REASONING_CHARS:
            raise ApiError(
                400, "REASONING_TOO_SHORT",
                f"Reasoning must be at least {config.MIN_REASONING_CHARS} characters.",
                field="creator_reasoning",
                detail={"min_chars": config.MIN_REASONING_CHARS,
                        "received": len(reasoning)},
            )
        if len(reasoning) > config.MAX_REASONING_CHARS:
            raise ApiError(
                400, "REASONING_TOO_LONG",
                f"Reasoning must be at most {config.MAX_REASONING_CHARS} characters.",
                field="creator_reasoning",
            )

        grounds = payload.get("grounds")
        if grounds is not None and grounds not in GROUNDS:
            raise ApiError(
                400, "INVALID_GROUNDS",
                "grounds must be one of: " + ", ".join(GROUNDS) + ".",
                field="grounds", detail={"allowed": list(GROUNDS)},
            )

        appeal_record = appeal_store.create(
            content_id, reasoning, grounds,
            payload.get("creator_id") or record.get("creator_id"),
            payload.get("evidence_url"),
        )

        # The original decision is not modified. A dispute is recorded, not
        # applied, so the audit chain still shows what was decided and why.
        original = {
            "verdict": record["verdict"],
            "ai_likelihood": record["ai_likelihood"],
            "confidence": record["confidence"],
            "analyzed_at": record["analyzed_at"],
        }
        updated = content_store.set_status(content_id, "under_review")

        audit_log = app.config["audit_log"]
        audit_log.append_appeal(
            content_id=content_id,
            appeal_id=appeal_record["appeal_id"],
            creator_id=appeal_record["creator_id"],
            reasoning=reasoning,
            grounds=grounds,
            contested_entry_id=audit_log.latest_decision_entry_id(content_id),
        )

        return jsonify({
            "received": True,
            "appeal_id": appeal_record["appeal_id"],
            "content_id": content_id,
            "status": "under_review",
            "message": "Appeal received. This content is now marked under review "
                       "and a person will look at it. The original result is "
                       "unchanged and remains on the record.",
            "filed_at": appeal_record["filed_at"],
            "original_decision": original,
            "label": generate_label(record["verdict"], record["confidence"],
                                    updated["status"]),
        }), 201

    @app.get("/content/<content_id>")
    @limiter.limit(config.CONTENT_RATE_LIMITS)
    def get_content(content_id):
        record = app.config["content_store"].get(content_id)
        if record is None:
            raise ApiError(404, "CONTENT_NOT_FOUND", "No such content id.")
        appeal_record = app.config["appeal_store"].get_for(content_id)
        return jsonify({
            "content_id": content_id,
            "status": record["status"],
            "verdict": record["verdict"],
            "confidence": record["confidence"],
            # Regenerated from current status, never stored. This is what lets
            # an appeal change what a reader sees without touching history.
            "label": generate_label(record["verdict"], record["confidence"],
                                    record["status"]),
            "analyzed_at": record["analyzed_at"],
            # The creator's reasoning is deliberately absent. This endpoint
            # serves readers; the reasoning is for reviewers.
            "appeal": None if appeal_record is None else {
                "appeal_id": appeal_record["appeal_id"],
                "filed_at": appeal_record["filed_at"],
                "status": appeal_record["status"],
            },
        }), 200

    @app.get("/log")
    @limiter.limit(config.LOG_RATE_LIMITS)
    def read_log():
        try:
            limit = int(request.args.get("limit", config.AUDIT_LOG_DEFAULT_LIMIT))
            offset = int(request.args.get("offset", 0))
        except ValueError:
            raise ApiError(
                400, "INVALID_TYPE", "limit and offset must be integers."
            )
        if limit < 1 or offset < 0:
            raise ApiError(
                400, "INVALID_TYPE", "limit must be positive and offset non-negative."
            )

        event = request.args.get("event")
        if event is not None and event not in ("decision", "appeal"):
            raise ApiError(
                400,
                "INVALID_TYPE",
                "event must be 'decision' or 'appeal'.",
                field="event",
            )

        order = request.args.get("order", "desc")
        if order not in ("desc", "asc"):
            raise ApiError(
                400, "INVALID_TYPE", "order must be 'desc' or 'asc'.", field="order"
            )

        entries, total = app.config["audit_log"].read(
            limit=limit,
            offset=offset,
            content_id=request.args.get("content_id"),
            event=event,
            order=order,
        )
        return jsonify(
            {
                "entries": [redact_for_public(e) for e in entries],
                "count": len(entries),
                "total": total,
                "order": order,
                "note": "Creator text fragments are redacted from this endpoint. "
                        "Full entries are on disk for authenticated reviewers.",
            }
        ), 200

    @app.get("/health")
    @limiter.exempt
    def health():
        return jsonify(
            {
                "status": "ok",
                "judge_available": bool(os.environ.get("GROQ_API_KEY")),
                "ruleset_version": config.RULESET_VERSION,
                "submissions_processed": app.config["content_store"].count(),
                "audit_entries": app.config["audit_log"].count(),
                "appeals_filed": app.config["appeal_store"].count(),
            }
        ), 200

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
