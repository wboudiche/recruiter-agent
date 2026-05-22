import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select

from recruiter.api import (
    applications, auth, candidates, chat, events, jobs, notifications, settings, sourcing,
)
from recruiter.api.origin_check import OriginCheckMiddleware
from recruiter.api.rate_limit import limiter
from recruiter.config import get_config
from recruiter.db import get_engine, get_session_factory
from recruiter.models import User

_log = logging.getLogger(__name__)


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
app.include_router(jobs.router)
app.include_router(auth.router)
app.include_router(candidates.router)
app.include_router(candidates.paste_router)
app.include_router(chat.router)
app.include_router(applications.router)
app.include_router(notifications.router)
app.include_router(settings.router)
app.include_router(events.router)
app.include_router(sourcing.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

