from fastapi import FastAPI

from recruiter.api import jobs

app = FastAPI(title="Recruiter Agent")
app.include_router(jobs.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
