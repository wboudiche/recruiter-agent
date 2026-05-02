import asyncio

import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult


@pytest.mark.asyncio
async def test_get_application_returns_404_when_missing(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/applications/9999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_applications_for_job(api_client: AsyncClient) -> None:
    job_id = (await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})).json()["id"]

    listing = await api_client.get(f"/api/jobs/{job_id}/applications")
    assert listing.status_code == 200
    assert listing.json() == []


@pytest.mark.asyncio
async def test_application_read_marks_linkedin_extracting_as_awaiting_paste(
    api_client: AsyncClient,
) -> None:
    """A LinkedIn URL submission stays in extracting and should expose
    awaiting_paste=True so the UI can prompt for a paste."""
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()
    try:
        job_id = (
            await api_client.post(
                "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
            )
        ).json()["id"]
        create = await api_client.post(
            f"/api/jobs/{job_id}/candidates",
            json={"kind": "url", "url": "https://www.linkedin.com/in/alice/"},
        )
        application_id = create.json()["application_id"]

        # Detail
        detail = await api_client.get(f"/api/applications/{application_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["stage"] == "extracting"
        assert body["awaiting_paste"] is True

        # Listing
        listing = await api_client.get(f"/api/jobs/{job_id}/applications")
        assert listing.status_code == 200
        rows = listing.json()
        assert len(rows) == 1
        assert rows[0]["awaiting_paste"] is True
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_application_read_non_linkedin_extracting_is_not_awaiting_paste(
    api_client: AsyncClient,
) -> None:
    """A paste-kind candidate that ends up in scored, observed before the
    background pipeline finishes (still in extracting) is non-LinkedIn so
    awaiting_paste must stay False."""
    # Use a FakeLLMClient that BLOCKS so the pipeline never advances past
    # extracting before we sample the read. We construct it without queued
    # responses so the first call raises and the row stays at extracting.
    fake = FakeLLMClient()  # no queued responses → call raises immediately
    app.dependency_overrides[get_llm] = lambda: fake
    try:
        job_id = (
            await api_client.post(
                "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
            )
        ).json()["id"]
        # paste kind without source_url → not LinkedIn
        create = await api_client.post(
            f"/api/jobs/{job_id}/candidates",
            json={"kind": "paste", "content": "Bob is a Python dev"},
        )
        application_id = create.json()["application_id"]

        # Best-effort: poll briefly. The application should be in extracting
        # (pipeline failed) — the relevant invariant for THIS test is that
        # awaiting_paste is False because the candidate is not a LinkedIn URL.
        body = None
        for _ in range(50):
            await asyncio.sleep(0.05)
            r = await api_client.get(f"/api/applications/{application_id}")
            body = r.json()
            if body["stage"] != "extracting":
                break
        assert body is not None
        assert body["awaiting_paste"] is False
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_application_read_linkedin_after_paste_is_not_awaiting_paste(
    api_client: AsyncClient,
) -> None:
    """Once a LinkedIn application has been advanced (e.g. to scored),
    awaiting_paste flips back to False because stage moved on."""
    fake = FakeLLMClient()
    app.dependency_overrides[get_llm] = lambda: fake
    try:
        job_id = (
            await api_client.post(
                "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
            )
        ).json()["id"]
        create = await api_client.post(
            f"/api/jobs/{job_id}/candidates",
            json={"kind": "url", "url": "https://www.linkedin.com/in/alice/"},
        )
        application_id = create.json()["application_id"]

        # Confirm starting state.
        first = await api_client.get(f"/api/applications/{application_id}")
        assert first.json()["awaiting_paste"] is True

        # Queue responses for the paste-triggered run, then submit paste.
        fake._structured.append(ExtractedCandidate(full_name="Alice", skills=["Rust"]))
        fake._structured.append(
            ScoreResult(
                score=60,
                breakdown=[ScoreBreakdownItem(criterion="x", weight=1.0, score=60, rationale="ok")],
                rationale="ok",
            )
        )
        await api_client.post(
            f"/api/applications/{application_id}/paste",
            json={"content": "Alice — pasted from LinkedIn — Rust"},
        )
        for _ in range(50):
            await asyncio.sleep(0.05)
            r = await api_client.get(f"/api/applications/{application_id}")
            if r.json()["stage"] == "scored":
                break
        body = r.json()
        assert body["stage"] == "scored"
        assert body["awaiting_paste"] is False
    finally:
        app.dependency_overrides.pop(get_llm, None)
