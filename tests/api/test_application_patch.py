import asyncio

import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult


def _fake_llm() -> FakeLLMClient:
    return FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice"),
            ScoreResult(
                score=70,
                breakdown=[ScoreBreakdownItem(criterion="x", weight=1.0, score=70, rationale="ok")],
                rationale="ok",
            ),
        ]
    )


async def _seed_scored_application(api_client: AsyncClient) -> int:
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
    return app_id


@pytest.mark.asyncio
async def test_patch_validate(api_client: AsyncClient) -> None:
    app.dependency_overrides[get_llm] = _fake_llm
    try:
        app_id = await _seed_scored_application(api_client)
        resp = await api_client.patch(
            f"/api/applications/{app_id}", json={"stage": "validated"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["stage"] == "validated"
        assert body["validated_at"] is not None
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_patch_unvalidate(api_client: AsyncClient) -> None:
    app.dependency_overrides[get_llm] = _fake_llm
    try:
        app_id = await _seed_scored_application(api_client)
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
        unvalidate = await api_client.patch(
            f"/api/applications/{app_id}", json={"stage": "scored"}
        )
        assert unvalidate.status_code == 200
        assert unvalidate.json()["stage"] == "scored"
        assert unvalidate.json()["validated_at"] is None
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_patch_reject_with_notes(api_client: AsyncClient) -> None:
    app.dependency_overrides[get_llm] = _fake_llm
    try:
        app_id = await _seed_scored_application(api_client)
        resp = await api_client.patch(
            f"/api/applications/{app_id}",
            json={"stage": "rejected", "notes": "[REJECTED] not enough Rust experience"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["stage"] == "rejected"
        assert body["notes"] == "[REJECTED] not enough Rust experience"
        assert body["rejected_at"] is not None
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_patch_reject_persists_structured_reason(api_client: AsyncClient) -> None:
    """Reject dialog sends `rejection_reason` (not stuffed into notes).
    Server stores it; read response surfaces it as a first-class field."""
    app.dependency_overrides[get_llm] = _fake_llm
    try:
        app_id = await _seed_scored_application(api_client)
        resp = await api_client.patch(
            f"/api/applications/{app_id}",
            json={
                "stage": "rejected",
                "rejection_reason": "Open to relocation but currently in Tunisia",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["stage"] == "rejected"
        assert body["rejection_reason"] == (
            "Open to relocation but currently in Tunisia"
        )
        # notes is NOT polluted with a [REJECTED] prefix anymore.
        assert body["notes"] is None or "[REJECTED]" not in (body["notes"] or "")
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_patch_unreject_clears_rejection_reason(api_client: AsyncClient) -> None:
    """Transitioning rejected → scored drops the stale reason so the
    detail page doesn't keep showing it on a now-active candidate."""
    app.dependency_overrides[get_llm] = _fake_llm
    try:
        app_id = await _seed_scored_application(api_client)
        # Reject with a reason
        await api_client.patch(
            f"/api/applications/{app_id}",
            json={"stage": "rejected", "rejection_reason": "cold"},
        )
        # Unreject
        resp = await api_client.patch(
            f"/api/applications/{app_id}", json={"stage": "scored"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["stage"] == "scored"
        assert body["rejection_reason"] is None
        assert body["rejected_at"] is None
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_patch_404_when_missing(api_client: AsyncClient) -> None:
    resp = await api_client.patch("/api/applications/9999", json={"stage": "validated"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_409_when_validating_from_extracting(api_client: AsyncClient) -> None:
    """Cannot validate while still extracting — only from scored."""
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()
    try:
        job_id = (
            await api_client.post(
                "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
            )
        ).json()["id"]
        # Create a LinkedIn URL → stays at extracting (no LLM calls)
        app_id = (
            await api_client.post(
                f"/api/jobs/{job_id}/candidates",
                json={"kind": "url", "url": "https://www.linkedin.com/in/alice/"},
            )
        ).json()["application_id"]
        resp = await api_client.patch(
            f"/api/applications/{app_id}", json={"stage": "validated"}
        )
        assert resp.status_code == 409
    finally:
        app.dependency_overrides.pop(get_llm, None)
