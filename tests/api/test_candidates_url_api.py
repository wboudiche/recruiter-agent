import asyncio

import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult


@pytest.mark.asyncio
async def test_add_candidate_via_paste_runs_pipeline(api_client: AsyncClient) -> None:
    job_resp = await api_client.post(
        "/api/jobs",
        json={"title": "Backend", "description": "Rust APIs", "criteria": [{"name": "Rust", "weight": 1.0, "description": "yrs"}]},
    )
    job_id = job_resp.json()["id"]

    fake = FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice", email="a@b.c", skills=["Rust"]),
            ScoreResult(
                score=88,
                breakdown=[ScoreBreakdownItem(criterion="Rust", weight=1.0, score=88, rationale="strong")],
                rationale="great",
            ),
        ]
    )
    app.dependency_overrides[get_llm] = lambda: fake

    try:
        resp = await api_client.post(
            f"/api/jobs/{job_id}/candidates",
            json={"kind": "paste", "content": "Alice — Rust"},
        )
        assert resp.status_code == 202, resp.text
        application_id = resp.json()["application_id"]

        for _ in range(50):
            await asyncio.sleep(0.05)
            r = await api_client.get(f"/api/applications/{application_id}")
            if r.json()["stage"] == "scored":
                break

        final = await api_client.get(f"/api/applications/{application_id}")
        body = final.json()
        assert body["stage"] == "scored"
        assert body["score"] == 88
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_add_candidate_via_linkedin_url_stays_extracting_until_paste(api_client: AsyncClient) -> None:
    job_resp = await api_client.post(
        "/api/jobs",
        json={"title": "T", "description": "D", "criteria": []},
    )
    job_id = job_resp.json()["id"]

    fake = FakeLLMClient()  # no responses queued — should not be called
    app.dependency_overrides[get_llm] = lambda: fake

    try:
        resp = await api_client.post(
            f"/api/jobs/{job_id}/candidates",
            json={"kind": "url", "url": "https://www.linkedin.com/in/alice/"},
        )
        assert resp.status_code == 202
        application_id = resp.json()["application_id"]

        await asyncio.sleep(0.1)
        r = await api_client.get(f"/api/applications/{application_id}")
        body = r.json()
        assert body["stage"] == "extracting"
        assert fake.calls == []
    finally:
        app.dependency_overrides.pop(get_llm, None)
