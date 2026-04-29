import asyncio
from pathlib import Path

import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult

PDF_FIXTURE = Path(__file__).parent.parent / "fixtures/resumes/sample.pdf"


@pytest.mark.asyncio
async def test_upload_pdf_resume_runs_pipeline(api_client: AsyncClient) -> None:
    job_resp = await api_client.post(
        "/api/jobs",
        json={"title": "Backend", "description": "Rust", "criteria": []},
    )
    job_id = job_resp.json()["id"]

    fake = FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice", skills=["Rust"]),
            ScoreResult(score=70, breakdown=[ScoreBreakdownItem(criterion="x", weight=1.0, score=70, rationale="ok")], rationale="ok"),
        ]
    )
    app.dependency_overrides[get_llm] = lambda: fake

    try:
        with PDF_FIXTURE.open("rb") as fh:
            resp = await api_client.post(
                f"/api/jobs/{job_id}/candidates/upload",
                files={"file": ("resume.pdf", fh, "application/pdf")},
            )
        assert resp.status_code == 202, resp.text
        application_id = resp.json()["application_id"]

        for _ in range(50):
            await asyncio.sleep(0.05)
            r = await api_client.get(f"/api/applications/{application_id}")
            if r.json()["stage"] == "scored":
                break

        final = await api_client.get(f"/api/applications/{application_id}")
        assert final.json()["stage"] == "scored"
        assert final.json()["score"] == 70
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_upload_unsupported_type_returns_415(api_client: AsyncClient) -> None:
    job_id = (await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})).json()["id"]
    resp = await api_client.post(
        f"/api/jobs/{job_id}/candidates/upload",
        files={"file": ("bad.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 415
