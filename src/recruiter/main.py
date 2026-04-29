from fastapi import FastAPI

app = FastAPI(title="Recruiter Agent")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
