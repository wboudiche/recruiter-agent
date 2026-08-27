from pathlib import Path

import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult

PDF_FIXTURE = Path(__file__).parent.parent / "fixtures/resumes/sample.pdf"


@pytest.mark.asyncio
async def test_download_resume_returns_uploaded_pdf_with_original_filename(
    api_client: AsyncClient,
) -> None:
    job_id = (
        await api_client.post(
            "/api/jobs", json={"title": "Backend", "description": "Rust", "criteria": []}
        )
    ).json()["id"]

    app.dependency_overrides[get_llm] = lambda: FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice"),
            ScoreResult(
                score=70,
                breakdown=[ScoreBreakdownItem(criterion="x", weight=1.0, score=70, rationale="ok")],
                rationale="ok",
            ),
        ]
    )
    try:
        with PDF_FIXTURE.open("rb") as fh:
            upload = await api_client.post(
                f"/api/jobs/{job_id}/candidates/upload",
                files={"file": ("Alice_Resume.pdf", fh, "application/pdf")},
            )
        candidate_id = upload.json()["application_id"]
        # application_id and candidate_id are assigned back-to-back on a
        # fresh upload but aren't guaranteed equal — look the real one up.
        app_resp = await api_client.get(f"/api/applications/{candidate_id}")
        candidate_id = app_resp.json()["candidate_id"]

        resp = await api_client.get(f"/api/candidates/{candidate_id}/resume")
        assert resp.status_code == 200, resp.text
        assert resp.content == PDF_FIXTURE.read_bytes()
        assert resp.headers["content-disposition"].startswith("inline;")
        # Original casing preserved, not lowercased by the upload's
        # case-insensitive extension check.
        assert "Alice_Resume.pdf" in resp.headers["content-disposition"]
        assert resp.headers["x-content-type-options"] == "nosniff"
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_download_resume_404_when_candidate_has_none(api_client: AsyncClient) -> None:
    job_id = (
        await api_client.post(
            "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
        )
    ).json()["id"]
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient(
        structured_responses=[ExtractedCandidate(full_name="Bob")]
    )
    try:
        app_id = (
            await api_client.post(
                f"/api/jobs/{job_id}/candidates", json={"kind": "paste", "content": "Bob"}
            )
        ).json()["application_id"]
        candidate_id = (await api_client.get(f"/api/applications/{app_id}")).json()["candidate_id"]

        resp = await api_client.get(f"/api/candidates/{candidate_id}/resume")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_download_resume_404_for_unknown_candidate(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/candidates/999999/resume")
    assert resp.status_code == 404
