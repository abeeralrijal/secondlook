"""Appeal store (planning.md section 4).

One appeal per content item. A second attempt is rejected rather than queued,
because appeals are not a channel for repeated pressure on a reviewer and one
appeal with real reasoning is worth more than five without.
"""

import threading
import uuid
from datetime import datetime, timezone

GROUNDS = (
    "wrote_by_hand",
    "ai_assisted_but_authored",
    "non_native_speaker",
    "genre_artifact",
    "other",
)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class AppealStore:
    def __init__(self):
        self._by_content = {}
        self._lock = threading.Lock()

    def exists_for(self, content_id):
        with self._lock:
            return content_id in self._by_content

    def create(self, content_id, reasoning, grounds=None, creator_id=None,
               evidence_url=None):
        record = {
            "appeal_id": str(uuid.uuid4()),
            "content_id": content_id,
            "reasoning": reasoning,
            "grounds": grounds,
            "creator_id": creator_id,
            "evidence_url": evidence_url,
            "filed_at": _now(),
            "status": "under_review",
        }
        with self._lock:
            self._by_content[content_id] = record
        return record

    def get_for(self, content_id):
        with self._lock:
            return self._by_content.get(content_id)

    def count(self):
        with self._lock:
            return len(self._by_content)
