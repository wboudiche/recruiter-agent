import asyncio

import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult


async def _create_scored_application(api_client: AsyncClient, *, job_id: int, score: int) -> int:
    fake = FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice"),
            ScoreResult(
                score=score,
                breakdown=[
                    ScoreBreakdownItem(criterion="x", weight=1.0, score=score, rationale="ok")
                ],
                rationale="initial",
            ),
        ]
    )
    app.dependency_overrides[get_llm] = lambda: fake
    try:
        app_id = (
            await api_client.post(
                f"/api/jobs/{job_id}/candidates", json={"kind": "paste", "content": "Alice"}
            )
        ).json()["application_id"]
        for _ in range(50):
            await asyncio.sleep(0.05)
            r = await api_client.get(f"/api/applications/{app_id}")
            if r.json()["stage"] == "scored":
                break
        assert r.json()["stage"] == "scored"
        assert r.json()["score"] == score
        return app_id
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_editing_criteria_rescores_existing_applications(api_client: AsyncClient) -> None:
    job_id = (
        await api_client.post(
            "/api/jobs",
            json={"title": "T", "description": "D", "criteria": [
                {"name": "Old", "weight": 1.0, "description": "old criterion"}
            ]},
        )
    ).json()["id"]
    app_id = await _create_scored_application(api_client, job_id=job_id, score=70)

    rescoring = FakeLLMClient(
        structured_responses=[
            ScoreResult(
                score=99,
                breakdown=[
                    ScoreBreakdownItem(
                        criterion="new", weight=1.0, score=99, rationale="better fit"
                    )
                ],
                rationale="rescored",
            ),
        ]
    )
    app.dependency_overrides[get_llm] = lambda: rescoring
    try:
        resp = await api_client.patch(
            f"/api/jobs/{job_id}",
            json={"criteria": [{"name": "New", "weight": 1.0, "description": "new criterion"}]},
        )
        assert resp.status_code == 200

        for _ in range(50):
            await asyncio.sleep(0.05)
            r = await api_client.get(f"/api/applications/{app_id}")
            if r.json()["score"] == 99:
                break
        assert r.json()["score"] == 99
        assert r.json()["score_rationale"] == "rescored"
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_editing_criteria_without_llm_configured_still_saves(api_client: AsyncClient) -> None:
    """No Settings row exists in this test DB, so get_llm would 503 if
    resolved eagerly. Saving criteria must still succeed (rescoring is
    best-effort and simply can't run without a configured provider)."""
    job_id = (
        await api_client.post(
            "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
        )
    ).json()["id"]

    resp = await api_client.patch(
        f"/api/jobs/{job_id}",
        json={"criteria": [{"name": "New", "weight": 1.0, "description": "new criterion"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["criteria"][0]["name"] == "New"


@pytest.mark.asyncio
async def test_editing_title_only_does_not_trigger_rescore(api_client: AsyncClient) -> None:
    job_id = (
        await api_client.post(
            "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
        )
    ).json()["id"]
    app_id = await _create_scored_application(api_client, job_id=job_id, score=70)

    # No structured_responses queued: if a rescore were (incorrectly)
    # triggered, the background task would hit "exhausted" and this
    # override wouldn't even be consulted for scoring since title-only
    # edits must not enqueue anything at all.
    exhausted = FakeLLMClient()
    app.dependency_overrides[get_llm] = lambda: exhausted
    try:
        resp = await api_client.patch(f"/api/jobs/{job_id}", json={"title": "T2"})
        assert resp.status_code == 200

        await asyncio.sleep(0.2)
        r = await api_client.get(f"/api/applications/{app_id}")
        assert r.json()["score"] == 70
        assert exhausted.calls == []
    finally:
        app.dependency_overrides.pop(get_llm, None)
