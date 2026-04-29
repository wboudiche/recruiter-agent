import asyncio

import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult


@pytest.mark.asyncio
async def test_paste_content_for_linkedin_application_runs_pipeline(api_client: AsyncClient) -> None:
    job_id = (await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})).json()["id"]

    fake = FakeLLMClient()
    app.dependency_overrides[get_llm] = lambda: fake
    try:
        create = await api_client.post(
            f"/api/jobs/{job_id}/candidates",
            json={"kind": "url", "url": "https://www.linkedin.com/in/alice/"},
        )
        application_id = create.json()["application_id"]

        # Now queue responses for the paste-triggered pipeline run
        fake._structured.append(ExtractedCandidate(full_name="Alice", skills=["Rust"]))
        fake._structured.append(
            ScoreResult(score=60, breakdown=[ScoreBreakdownItem(criterion="x", weight=1.0, score=60, rationale="ok")], rationale="ok")
        )

        resp = await api_client.post(
            f"/api/applications/{application_id}/paste",
            json={"content": "Alice — pasted from LinkedIn — Rust"},
        )
        assert resp.status_code == 202

        for _ in range(50):
            await asyncio.sleep(0.05)
            r = await api_client.get(f"/api/applications/{application_id}")
            if r.json()["stage"] == "scored":
                break
        assert r.json()["stage"] == "scored"
    finally:
        app.dependency_overrides.pop(get_llm, None)
