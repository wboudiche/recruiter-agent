"""Undo-token store for one-shot stage reversals.

Two backends share the same interface (Protocol `UndoStore`):
  - `InMemoryUndoStore` — process-local dict, lost on restart. Default.
  - `RedisUndoStore` — survives restarts and works across pods. Activates
    when `RECRUITER_REDIS_URL` is set in config.

Both use one-shot consume semantics: the token is destroyed on first use.
The cross-app guard (consume(token, application_id=...)) preserves the
token if the requested application_id doesn't match what was issued.
"""
import json
import secrets
import time
from threading import Lock
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class UndoStore(Protocol):
    """Token store for one-shot reversals. See module docstring."""

    def issue(
        self,
        *,
        application_id: int,
        payload: dict[str, Any] | None = None,
        previous_stage: str | None = None,
    ) -> str: ...

    def consume(
        self,
        token: str,
        *,
        application_id: int | None = None,
    ) -> dict | None: ...


class InMemoryUndoStore:
    """Process-local dict-backed UndoStore. Tokens are lost on restart,
    which is acceptable — the user just loses the Undo button for that
    turn. Audit history persists in chat_messages and event_logs."""

    def __init__(self, ttl_seconds: float = 900.0) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[str, tuple[float, dict]] = {}
        self._lock = Lock()

    def issue(self, *, application_id, payload=None, previous_stage=None):
        if payload is None:
            if previous_stage is None:
                raise ValueError("issue requires payload or previous_stage")
            payload = {"previous_stage": previous_stage}
        body = {"application_id": application_id, **payload}
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._entries[token] = (time.monotonic(), body)
        return token

    def consume(self, token, *, application_id=None):
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


class RedisUndoStore:
    """Redis-backed UndoStore. Survives restarts and shares state across
    pods. Uses SETEX for TTL + a single GETDEL-style consume flow that's
    safe under concurrency.

    Synchronous redis-py client because issue/consume happen at most a
    few times per chat turn and Redis round-trips are sub-millisecond.
    Switch to redis.asyncio if profiling ever shows event-loop contention.
    """

    KEY_PREFIX = "recruiter:undo:"

    def __init__(self, redis_url: str, ttl_seconds: int = 900) -> None:
        # Imported here so the dep is only loaded when actually used.
        import redis

        self._client = redis.Redis.from_url(redis_url, decode_responses=True)
        self._ttl = ttl_seconds

    def _key(self, token: str) -> str:
        return f"{self.KEY_PREFIX}{token}"

    def issue(self, *, application_id, payload=None, previous_stage=None):
        if payload is None:
            if previous_stage is None:
                raise ValueError("issue requires payload or previous_stage")
            payload = {"previous_stage": previous_stage}
        body = {"application_id": application_id, **payload}
        token = secrets.token_urlsafe(24)
        self._client.setex(self._key(token), self._ttl, json.dumps(body))
        return token

    def consume(self, token, *, application_id=None):
        key = self._key(token)
        # Peek first to support the cross-app guard. If app_id doesn't
        # match, leave the entry in place. Race window between GET and
        # DELETE is small; worst case is the rightful owner sees None
        # if they redeem in that microsecond — acceptable for an Undo
        # button.
        raw = self._client.get(key)
        if raw is None:
            return None
        payload = json.loads(raw)
        if application_id is not None and payload.get("application_id") != application_id:
            return None
        # GETDEL is atomic; use it instead of separate DELETE so two
        # concurrent consumers can't both succeed.
        consumed = self._client.getdel(key)
        if consumed is None:
            return None
        return json.loads(consumed)


_default: UndoStore | None = None


def get_default_undo_store() -> UndoStore:
    """Return the process-default UndoStore, picking impl from config.

    First call decides; subsequent calls return the same instance. To pick
    up a config change, restart the process.
    """
    global _default
    if _default is None:
        from recruiter.config import get_config

        cfg = get_config()
        redis_url = getattr(cfg, "redis_url", None)
        if redis_url:
            _default = RedisUndoStore(redis_url=redis_url, ttl_seconds=900)
        else:
            _default = InMemoryUndoStore(ttl_seconds=900.0)
    return _default
