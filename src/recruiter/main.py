from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from recruiter.api import applications, auth, candidates, chat, events, jobs, notifications, settings
from recruiter.api.rate_limit import limiter

app = FastAPI(title="Recruiter Agent")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(jobs.router)
app.include_router(candidates.router)
app.include_router(candidates.paste_router)
app.include_router(chat.router)
app.include_router(applications.router)
app.include_router(auth.router)
app.include_router(notifications.router)
app.include_router(settings.router)
app.include_router(events.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
