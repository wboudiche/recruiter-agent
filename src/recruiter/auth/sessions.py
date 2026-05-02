import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.models import AuthSession, User

_IDLE_BUMP_THRESHOLD = timedelta(hours=1)


async def create_session(
    session: AsyncSession, *, user_id: int, ttl_days: int,
    user_agent: str | None = None, ip: str | None = None,
) -> str:
    """Insert a new auth_sessions row and return the opaque token."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    row = AuthSession(
        id=token, user_id=user_id,
        expires_at=now + timedelta(days=ttl_days),
        last_seen_at=now, user_agent=user_agent, ip=ip,
    )
    session.add(row)
    await session.commit()
    return token


async def lookup_session(session: AsyncSession, *, token: str) -> User | None:
    """Return the User behind an active token, or None if missing/expired."""
    if not token:
        return None
    row = (await session.execute(
        select(AuthSession)
        .where(AuthSession.id == token)
        .where(AuthSession.expires_at > datetime.now(timezone.utc))
    )).scalar_one_or_none()
    if row is None:
        return None
    return await session.get(User, row.user_id)


async def touch_session(
    session: AsyncSession, *, token: str, ttl_days: int,
) -> bool:
    """Slide the session window if the last bump was over an hour ago.

    Returns True if a bump happened, False otherwise. Throttled to once
    per hour to avoid hot-write contention on every authenticated request.
    """
    row = await session.get(AuthSession, token)
    if row is None:
        return False
    now = datetime.now(timezone.utc)
    last_seen = row.last_seen_at
    # asyncpg + SQLAlchemy occasionally hand back tz-naive datetimes after a
    # refresh; reattach UTC so the subtraction below doesn't TypeError.
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    if (now - last_seen) < _IDLE_BUMP_THRESHOLD:
        return False
    row.last_seen_at = now
    row.expires_at = now + timedelta(days=ttl_days)
    await session.commit()
    return True


async def revoke_session(session: AsyncSession, *, token: str) -> None:
    """Delete the session row. No-op if the token doesn't exist."""
    await session.execute(delete(AuthSession).where(AuthSession.id == token))
    await session.commit()
