from fastapi import FastAPI

from recruiter.api import applications, candidates, events, jobs, settings

app = FastAPI(title="Recruiter Agent")
app.include_router(jobs.router)
app.include_router(candidates.router)
app.include_router(candidates.paste_router)
app.include_router(applications.router)
app.include_router(settings.router)
app.include_router(events.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
