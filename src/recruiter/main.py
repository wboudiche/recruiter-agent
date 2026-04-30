from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from recruiter.api import applications, candidates, events, jobs, settings

app = FastAPI(title="Recruiter Agent")
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
app.include_router(applications.router)
app.include_router(settings.router)
app.include_router(events.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
