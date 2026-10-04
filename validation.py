"""Request validation for POST /submit (planning.md sections 3 and 6).

Everything downstream may assume valid, analyzable text, so no component after
this one repeats a length check.
"""

import config
from errors import ApiError


def _require_string(payload, field, required=True, max_chars=None):
    if field not in payload or payload[field] is None:
        if required:
            raise ApiError(
                400, "MISSING_FIELD", f"'{field}' is required.", field=field
            )
        return None

    value = payload[field]
    if not isinstance(value, str):
        raise ApiError(
            400,
            "INVALID_TYPE",
            f"'{field}' must be a string.",
            field=field,
            detail={"received_type": type(value).__name__},
        )

    if max_chars is not None and len(value) > max_chars:
        raise ApiError(
            400,
            "INVALID_TYPE",
            f"'{field}' must be at most {max_chars} characters.",
            field=field,
            detail={"max_chars": max_chars, "received": len(value)},
        )
    return value


def validate_submission(payload):
    """Return a normalized submission dict or raise ApiError."""
    if not isinstance(payload, dict):
        raise ApiError(400, "INVALID_TYPE", "Request body must be a JSON object.")

    text = _require_string(payload, "text")

    # Normalize before measuring. A body padded with whitespace must not clear
    # the minimum on whitespace alone.
    normalized = "\n\n".join(
        " ".join(block.split())
        for block in text.replace("\r\n", "\n").split("\n\n")
        if block.strip()
    )

    if len(normalized) < config.MIN_TEXT_CHARS:
        raise ApiError(
            400,
            "TEXT_TOO_SHORT",
            f"Text must be at least {config.MIN_TEXT_CHARS} characters.",
            field="text",
            detail={"min_chars": config.MIN_TEXT_CHARS, "received": len(normalized)},
        )

    if len(normalized) > config.MAX_TEXT_CHARS:
        raise ApiError(
            400,
            "TEXT_TOO_LONG",
            f"Text must be at most {config.MAX_TEXT_CHARS} characters.",
            field="text",
            detail={"max_chars": config.MAX_TEXT_CHARS, "received": len(normalized)},
        )

    creator_id = _require_string(
        payload, "creator_id", required=False, max_chars=config.MAX_CREATOR_ID_CHARS
    )

    content_type = payload.get("content_type") or config.DEFAULT_CONTENT_TYPE
    if content_type not in config.ALLOWED_CONTENT_TYPES:
        raise ApiError(
            400,
            "INVALID_CONTENT_TYPE",
            "content_type must be one of: "
            + ", ".join(config.ALLOWED_CONTENT_TYPES)
            + ".",
            field="content_type",
            detail={"allowed": list(config.ALLOWED_CONTENT_TYPES)},
        )

    return {
        "text": normalized,
        "creator_id": creator_id,
        "content_type": content_type,
    }
