import secrets
import time
from threading import Lock


class UndoStore:
    """In-memory token store for one-shot stage reversals.

    Process-local: tokens are lost on restart, which is acceptable — the user
    just loses the Undo button for that turn. Audit history persists in
    chat_messages and event_logs.
    """

    def __init__(self, ttl_seconds: float = 900.0) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[str, tuple[float, dict]] = {}
        self._lock = Lock()

    def issue(self, *, application_id: int, previous_stage: str) -> str:
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._entries[token] = (time.monotonic(), {
                "application_id": application_id,
                "previous_stage": previous_stage,
            })
        return token

    def consume(self, token: str) -> dict | None:
        with self._lock:
            entry = self._entries.pop(token, None)
        if entry is None:
            return None
        issued_at, payload = entry
        if time.monotonic() - issued_at > self._ttl:
            return None
        return payload


_default = UndoStore(ttl_seconds=900.0)


def get_default_undo_store() -> UndoStore:
    return _default
