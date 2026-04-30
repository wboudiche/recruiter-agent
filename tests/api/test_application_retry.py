import asyncio

import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult


@pytest.mark.asyncio
async def test_retry_resets_stage_and_reruns_pipeline(api_client: AsyncClient) -> None:
    # First: create a candidate with a fake that fails (raises on chat_structured)
    failing = FakeLLMClient()  # exhausted -> RuntimeError
    app.dependency_overrides[get_llm] = lambda: failing
    try:
        job_id = (
            await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})
        ).json()["id"]
        app_id = (
            await api_client.post(
                f"/api/jobs/{job_id}/candidates", json={"kind": "paste", "content": "Alice"}
            )
        ).json()["application_id"]
        # The orchestrator's exception path leaves stage at extracting and writes EventLog.
        await asyncio.sleep(0.3)
        r = await api_client.get(f"/api/applications/{app_id}")
        assert r.json()["stage"] == "extracting"
    finally:
        app.dependency_overrides.pop(get_llm, None)

    # Now swap in a working fake and retry
    working = FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice"),
            ScoreResult(
                score=80,
                breakdown=[ScoreBreakdownItem(criterion="x", weight=1.0, score=80, rationale="ok")],
                rationale="ok",
            ),
        ]
    )
    app.dependency_overrides[get_llm] = lambda: working
    try:
        resp = await api_client.post(f"/api/applications/{app_id}/retry")
        assert resp.status_code == 202
        for _ in range(50):
            await asyncio.sleep(0.05)
            r = await api_client.get(f"/api/applications/{app_id}")
            if r.json()["stage"] == "scored":
                break
        assert r.json()["stage"] == "scored"
        assert r.json()["score"] == 80
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_retry_404_when_missing(api_client: AsyncClient) -> None:
    # FastAPI resolves get_llm before the handler runs; override so we hit the 404 branch.
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()
    try:
        resp = await api_client.post("/api/applications/9999/retry")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_retry_409_when_already_scored(api_client: AsyncClient) -> None:
    fake = FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice"),
            ScoreResult(
                score=70,
                breakdown=[ScoreBreakdownItem(criterion="x", weight=1.0, score=70, rationale="ok")],
                rationale="ok",
            ),
        ]
    )
    app.dependency_overrides[get_llm] = lambda: fake
    try:
        job_id = (
            await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})
        ).json()["id"]
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

        resp = await api_client.post(f"/api/applications/{app_id}/retry")
        assert resp.status_code == 409
    finally:
        app.dependency_overrides.pop(get_llm, None)
