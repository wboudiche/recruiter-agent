from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from recruiter.auth import dev_bypass
from recruiter.auth.sessions import lookup_session, touch_session
from recruiter.config import get_config
from recruiter.db import get_engine
from recruiter.models import User


async def get_session() -> AsyncIterator[AsyncSession]:
    engine = get_engine(get_config().database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session


@asynccontextmanager
async def streaming_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Open a fresh DB session for use INSIDE a `StreamingResponse` body.

    The request-scoped `get_session` dep closes its session as soon as the
    handler returns — i.e., BEFORE the streaming generator runs. Streaming
    endpoints must therefore create their own session via this helper.
    """
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session


async def require_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    """Resolve the logged-in User or raise 401. Mounts on every gated route.

    Order:
      1. Dev bypass (only if no IdP configured).
      2. Cookie → session lookup → user.
      3. Sliding-window touch (throttled to once per hour).
    """
    bypass_user = await dev_bypass.maybe_resolve(session)
    if bypass_user is not None:
        return bypass_user

    cookie = request.cookies.get("recruiter_session")
    if not cookie:
        raise HTTPException(status_code=401, detail="not authenticated")
    user = await lookup_session(session, token=cookie)
    if user is None:
        raise HTTPException(status_code=401, detail="session expired")

    cfg = get_config()
    await touch_session(session, token=cookie, ttl_days=cfg.session_ttl_days)
    return user
