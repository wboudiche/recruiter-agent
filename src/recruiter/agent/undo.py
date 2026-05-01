import secrets
import time
from threading import Lock
from typing import Any


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

    def issue(self, *, application_id: int, payload: dict[str, Any] | None = None,
              previous_stage: str | None = None) -> str:
        """Issue a one-shot token. Either pass a full `payload` (preferred for
        write tools that need to snapshot extra state like timestamps), or a
        bare `previous_stage` (back-compat shortcut)."""
        if payload is None:
            if previous_stage is None:
                raise ValueError("issue requires payload or previous_stage")
            payload = {"previous_stage": previous_stage}
        body = {"application_id": application_id, **payload}
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._entries[token] = (time.monotonic(), body)
        return token

    def consume(self, token: str, *, application_id: int | None = None) -> dict | None:
        """One-shot consume. If `application_id` is provided and doesn't match
        the entry's, leave the entry in place and return None — prevents a
        cross-app POST from burning a legitimate token."""
        with self._lock:
            entry = self._entries.get(token)
            if entry is None:
                return None
            issued_at, payload = entry
            if time.monotonic() - issued_at > self._ttl:
                self._entries.pop(token, None)
                return None
            if application_id is not None and payload.get("application_id") != application_id:
                # Mismatch — preserve the entry for its rightful owner.
                return None
            self._entries.pop(token, None)
        return payload


_default = UndoStore(ttl_seconds=900.0)


def get_default_undo_store() -> UndoStore:
    return _default
