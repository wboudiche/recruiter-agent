from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.auth.sessions import (
    create_session,
    lookup_session,
    revoke_session,
    touch_session,
)
from recruiter.models import AuthSession, User


async def _seed_user(session: AsyncSession, email: str = "alice@acme.com") -> int:
    user = User(email=email, sub=f"sub-{email}", issuer="x")
    session.add(user); await session.commit()
    return user.id


@pytest.mark.asyncio
async def test_create_session_returns_token_and_persists_row(db_session_with_schema: AsyncSession) -> None:
    user_id = await _seed_user(db_session_with_schema)
    token = await create_session(db_session_with_schema, user_id=user_id, ttl_days=7)
    assert isinstance(token, str) and len(token) >= 32
    row = await db_session_with_schema.get(AuthSession, token)
    assert row is not None
    assert row.user_id == user_id


@pytest.mark.asyncio
async def test_lookup_session_returns_user_when_active(db_session_with_schema: AsyncSession) -> None:
    user_id = await _seed_user(db_session_with_schema)
    token = await create_session(db_session_with_schema, user_id=user_id, ttl_days=7)
    user = await lookup_session(db_session_with_schema, token=token)
    assert user is not None
    assert user.id == user_id


@pytest.mark.asyncio
async def test_lookup_session_returns_none_for_expired(db_session_with_schema: AsyncSession) -> None:
    user_id = await _seed_user(db_session_with_schema)
    token = await create_session(db_session_with_schema, user_id=user_id, ttl_days=7)
    row = await db_session_with_schema.get(AuthSession, token)
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session_with_schema.commit()
    assert await lookup_session(db_session_with_schema, token=token) is None


@pytest.mark.asyncio
async def test_lookup_session_returns_none_for_unknown_token(db_session_with_schema: AsyncSession) -> None:
    assert await lookup_session(db_session_with_schema, token="not-a-token") is None


@pytest.mark.asyncio
async def test_revoke_session_deletes_row(db_session_with_schema: AsyncSession) -> None:
    user_id = await _seed_user(db_session_with_schema)
    token = await create_session(db_session_with_schema, user_id=user_id, ttl_days=7)
    await revoke_session(db_session_with_schema, token=token)
    assert await db_session_with_schema.get(AuthSession, token) is None


@pytest.mark.asyncio
async def test_revoke_unknown_token_is_noop(db_session_with_schema: AsyncSession) -> None:
    # Should not raise.
    await revoke_session(db_session_with_schema, token="not-a-token")


@pytest.mark.asyncio
async def test_touch_session_extends_expiry_when_idle(db_session_with_schema: AsyncSession) -> None:
    user_id = await _seed_user(db_session_with_schema)
    token = await create_session(db_session_with_schema, user_id=user_id, ttl_days=7)
    row = await db_session_with_schema.get(AuthSession, token)
    # Pretend last_seen_at was 2h ago — should bump.
    old_seen = datetime.now(timezone.utc) - timedelta(hours=2)
    row.last_seen_at = old_seen
    row.expires_at = old_seen + timedelta(days=7)
    await db_session_with_schema.commit()
    bumped = await touch_session(db_session_with_schema, token=token, ttl_days=7)
    assert bumped is True
    refreshed = await db_session_with_schema.get(AuthSession, token)
    assert refreshed.last_seen_at > old_seen


@pytest.mark.asyncio
async def test_touch_session_skips_when_recent(db_session_with_schema: AsyncSession) -> None:
    user_id = await _seed_user(db_session_with_schema)
    token = await create_session(db_session_with_schema, user_id=user_id, ttl_days=7)
    bumped = await touch_session(db_session_with_schema, token=token, ttl_days=7)
    assert bumped is False  # last_seen_at is fresh; no bump needed.
