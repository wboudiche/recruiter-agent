from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from recruiter.api import (
    applications, auth, candidates, chat, events, jobs, notifications, settings,
)
from recruiter.api.origin_check import OriginCheckMiddleware
from recruiter.api.rate_limit import limiter
from recruiter.config import get_config

app = FastAPI(title="Recruiter Agent")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

