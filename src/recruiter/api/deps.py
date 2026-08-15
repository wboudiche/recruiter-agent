import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, HTTPException, Request

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from recruiter.api.permissions import MUTATING_METHODS, VIEWER_ALLOWED_ROUTES
from recruiter.auth import dev_bypass
from recruiter.auth.sessions import lookup_session, touch_session
from recruiter.config import get_config
from recruiter.db import get_engine
from recruiter.models import Role, User


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


async def maybe_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User | None:
    """Resolve the logged-in User, or None. NEVER raises.

    Split out of `require_user` so the app-level read-only guard can ask
    "who is this?" without forcing authentication — the guard runs on
    every route including public ones, and a raising resolver there would
    401 the login page.

    FastAPI caches dependencies per request, so a route that also depends
    on `require_user` resolves this once, not twice: no extra session
    lookup is introduced by the guard.
    """
    bypass_user = await dev_bypass.maybe_resolve(session)
    if bypass_user is not None:
        return bypass_user if bypass_user.is_active else None

    cookie = request.cookies.get("recruiter_session")
    if not cookie:
        return None
    user = await lookup_session(session, token=cookie)
    if user is None or not user.is_active:
        return None

    cfg = get_config()
    # Sliding-window bump is best-effort: a transient DB hiccup must not
    # 500 an otherwise-authenticated user. Throttled to once/hour anyway.
    try:
        await touch_session(session, token=cookie, ttl_days=cfg.session_ttl_days)
    except Exception:
        logger.warning("touch_session failed; continuing without bump", exc_info=True)
    return user


async def require_user(user: User | None = Depends(maybe_user)) -> User:
    """Resolve the logged-in User or raise 401. Mounts on every gated route."""
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


def require_role(*allowed: Role):
    """Gate a route on role. Layers on `require_user`, so the 401 path is
    unchanged and only the 403 is new."""

    async def _guard(user: User = Depends(require_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail="insufficient role")
        return user

    return _guard


def _route_template(request: Request) -> str | None:
    """The matched route's template, e.g. /api/applications/{id}/chat.

    App-level dependencies run AFTER routing, so the resolved route is on
    the scope. Matching the template rather than the concrete path means
    ids embedded in URLs never need a regex.
    """
    route = request.scope.get("route")
    return getattr(route, "path", None)


async def viewer_readonly_guard(
    request: Request,
    user: User | None = Depends(maybe_user),
) -> None:
    """Refuse mutations to viewers unless the route is allowlisted.

    Registered app-wide, so a router that does not exist yet is covered
    the day it is added. Anonymous callers pass straight through: this
    enforces role, not authentication, and the route's own dependencies
    still return 401 where they should.
    """
    if user is None or user.role != Role.VIEWER:
        return
    if request.method not in MUTATING_METHODS:
        return
    template = _route_template(request)
    if template and (request.method, template) in VIEWER_ALLOWED_ROUTES:
        return
    raise HTTPException(status_code=403, detail="read-only role")
