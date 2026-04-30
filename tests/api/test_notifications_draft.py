import asyncio

import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult
from recruiter.schemas.notification import DraftedEmail


async def _seed_validated_app(api_client: AsyncClient) -> int:
    job_id = (
        await api_client.post(
            "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
        )
    ).json()["id"]
    app_id = (
        await api_client.post(
            f"/api/jobs/{job_id}/candidates",
            json={"kind": "paste", "content": "Alice — Rust"},
        )
    ).json()["application_id"]
    for _ in range(50):
        await asyncio.sleep(0.05)
        r = await api_client.get(f"/api/applications/{app_id}")
        if r.json()["stage"] == "scored":
            break
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
    return app_id


@pytest.mark.asyncio
async def test_draft_email_endpoint(api_client: AsyncClient) -> None:
    fake = FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice", email="alice@example.com", skills=["Rust"]),
            ScoreResult(
                score=85,
                breakdown=[
                    ScoreBreakdownItem(criterion="Rust", weight=1.0, score=85, rationale="ok")
                ],
                rationale="ok",
            ),
            DraftedEmail(subject="Interview", body="Hi Alice"),
        ]
    )
    app.dependency_overrides[get_llm] = lambda: fake
    try:
        app_id = await _seed_validated_app(api_client)
        resp = await api_client.post(
            f"/api/applications/{app_id}/draft-email",
            json={
                "slots": [
                    {
                        "start": "2026-05-01T10:00:00+00:00",
                        "end": "2026-05-01T11:00:00+00:00",
                    }
                ]
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["subject"] == "Interview"
        assert body["body"] == "Hi Alice"
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_draft_email_404_when_application_missing(api_client: AsyncClient) -> None:
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()
    try:
        resp = await api_client.post(
            "/api/applications/9999/draft-email",
            json={
                "slots": [
                    {"start": "2026-05-01T10:00:00+00:00", "end": "2026-05-01T11:00:00+00:00"}
                ]
            },
        )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_llm, None)
