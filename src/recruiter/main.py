import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select

from recruiter.api import (
    applications, auth, candidates, chat, events, jobs, notifications, settings, sourcing, users,
)
from recruiter.api.deps import viewer_readonly_guard
from recruiter.api.origin_check import OriginCheckMiddleware
from recruiter.api.rate_limit import limiter
from recruiter.config import get_config
from recruiter.db import get_engine, get_session_factory
from recruiter.logging_config import configure_logging
from recruiter.models import Role, User

_log = logging.getLogger(__name__)

# Applied at import, before any router module logs anything. Without this
# the root logger stays at WARNING with no handler, and every
# `logger.info(...)` in the app — including the user-management audit
# trail — is discarded, while uvicorn's own request lines still appear.
configure_logging(get_config().log_level)


async def _seed_default_user() -> None:
    cfg = get_config()
    if not (cfg.default_account_email and cfg.default_account_password):
        return
    canonical_email = cfg.default_account_email.strip().lower()
    sub = f"default:{canonical_email}"
    engine = get_engine(cfg.database_url)
    SessionLocal = get_session_factory(engine)
    try:
        async with SessionLocal() as session:
            existing = (await session.execute(
                select(User).where(User.issuer == "default").where(User.sub == sub)
            )).scalar_one_or_none()
            if existing is not None:
                return
            session.add(User(
                email=canonical_email, sub=sub, issuer="default", name="Default Admin",
                role=Role.ADMIN,
            ))
            await session.commit()
            _log.info("seeded default user %s", canonical_email)
    except Exception:
        # Don't block startup if seeding fails (e.g. transient DB issue);
        # the lazy path in auth.py still creates the row on first login.
        _log.exception("default-user seeding failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await _seed_default_user()
    yield


app = FastAPI(title="Recruiter Agent", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

_cfg = get_config()
_origins = [o.strip() for o in _cfg.allowed_origins.split(",") if o.strip()]

app.add_middleware(OriginCheckMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,  # was False; cookies must flow cross-origin in dev
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Every /api/* router is mounted through this umbrella so the read-only
# guard covers routers added later without anyone remembering to opt in.
# NOT applied to `app` directly: that would also gate /health (below),
# which must answer liveness probes without ever touching the database.
# See api/permissions.py for the policy.
#
# IMPORTANT — this guarantee only holds if EVERY new router is added here
# via `_api_router.include_router(...)`, never `app.include_router(...)`
# directly (the pattern used elsewhere in this file for non-API routes).
# A router mounted on `app` bypasses the guard entirely and ships open to
# viewers. `tests/api/test_viewer_matrix.py` enforces this at test time —
# it is not enforced by the framework — so a new router with no matching
# test coverage is the one way this can silently regress.
_api_router = APIRouter(dependencies=[Depends(viewer_readonly_guard)])
_api_router.include_router(jobs.router)
_api_router.include_router(auth.router)
_api_router.include_router(candidates.router)
_api_router.include_router(candidates.paste_router)
_api_router.include_router(chat.router)
_api_router.include_router(applications.router)
_api_router.include_router(notifications.router)
_api_router.include_router(settings.router)
_api_router.include_router(events.router)
_api_router.include_router(sourcing.router)
_api_router.include_router(users.router)
app.include_router(_api_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

