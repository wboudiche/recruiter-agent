from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.models import AuthSession, OAuthState, User


@pytest.mark.asyncio
async def test_user_roundtrip(db_session_with_schema: AsyncSession) -> None:
    user = User(email="alice@acme.com", sub="g-12345",
                issuer="https://accounts.google.com", name="Alice", picture=None)
    db_session_with_schema.add(user)
    await db_session_with_schema.commit()
    fetched = (await db_session_with_schema.execute(select(User))).scalar_one()
    assert fetched.email == "alice@acme.com"
    assert fetched.sub == "g-12345"


@pytest.mark.asyncio
async def test_auth_session_roundtrip(db_session_with_schema: AsyncSession) -> None:
    user = User(email="alice@acme.com", sub="g-1", issuer="x")
    db_session_with_schema.add(user); await db_session_with_schema.flush()
    now = datetime.now(timezone.utc)
    sess = AuthSession(
        id="tok-abc", user_id=user.id, expires_at=now + timedelta(days=7),
        last_seen_at=now, user_agent=None, ip=None,
    )
    db_session_with_schema.add(sess); await db_session_with_schema.commit()
    fetched = await db_session_with_schema.get(AuthSession, "tok-abc")
    assert fetched is not None
    assert fetched.user_id == user.id


@pytest.mark.asyncio
async def test_oauth_state_roundtrip(db_session_with_schema: AsyncSession) -> None:
    state = OAuthState(state="abc", nonce="xyz", pkce_verifier="ver", next_url="/jobs")
    db_session_with_schema.add(state); await db_session_with_schema.commit()
    fetched = await db_session_with_schema.get(OAuthState, "abc")
    assert fetched is not None
    assert fetched.next_url == "/jobs"


@pytest.mark.asyncio
async def test_session_cascade_on_user_delete(db_session_with_schema: AsyncSession) -> None:
    user = User(email="bob@acme.com", sub="g-2", issuer="x")
    db_session_with_schema.add(user); await db_session_with_schema.flush()
    now = datetime.now(timezone.utc)
    sess = AuthSession(id="t1", user_id=user.id, expires_at=now + timedelta(days=7),
                       last_seen_at=now)
    db_session_with_schema.add(sess); await db_session_with_schema.commit()
    await db_session_with_schema.delete(user); await db_session_with_schema.commit()
    assert await db_session_with_schema.get(AuthSession, "t1") is None
