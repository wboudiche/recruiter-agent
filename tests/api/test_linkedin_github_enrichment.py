"""LinkedIn add → GitHub-by-name enrichment behaviour."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from httpx import AsyncClient

from recruiter.api import candidates as candidates_api
from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.pipeline.enrichers import linkedin_via_github
from recruiter.pipeline.enrichers.github_by_name import name_matches
from recruiter.pipeline.parsers.text import ParsedContent
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult


@pytest.mark.parametrize(
    "candidate,github_name,github_login,expected",
    [
        ("Sergey Stepanyan", "Sergey Stepanyan", None, True),
        ("Marie Laval", "Marie LAVAL", None, True),
        ("Andrej Karpathy", "Andrej Karpathy", None, True),
        # The login-rescue case: GitHub name is only "Andrej" but the
        # login carries the surname. Without considering the login the
        # candidate would be wrongly rejected.
        ("Andrej Karpathy", "Andrej", "karpathy", True),
        # Single-token candidate names must NOT match — too many GitHub
        # users with common first names.
        ("Andrej", "Andrej Karpathy", "karpathy", False),
        # Only one overlapping token (first name only).
        ("Sergey Stepanyan", "Sergey Vasiliev", "svas", False),
        # Empty / missing.
        (None, "Marie Laval", None, False),
        ("Marie Laval", None, None, False),
        ("", "x y", None, False),
    ],
)
def test_name_matches_heuristic(candidate, github_name, github_login, expected) -> None:
    assert name_matches(candidate, github_name, github_login=github_login) is expected


# ---------- end-to-end add-path tests ------------------------------------

class _StubLLM(FakeLLMClient):
    """LLM stub that returns a populated extraction + score so the
    GitHub-pipeline branch transitions the application out of EXTRACTING."""

    pass


def _patch_search_returns(monkeypatch, github_url: str | None) -> dict[str, Any]:
    """Bypass network. Returns the captured GitHub URL the enricher sees."""
    captured: dict[str, Any] = {"asked_for": None, "github_url_returned": github_url}

    async def fake_find(name: str, **_kwargs: Any) -> str | None:
        captured["asked_for"] = name
        return github_url

    monkeypatch.setattr(linkedin_via_github, "find_github_url_for_name", fake_find)
    return captured


def _patch_fetch_github(monkeypatch, text: str) -> None:
    async def fake_fetch_github(url: str, **_kwargs: Any) -> ParsedContent:
        return ParsedContent(
            text=text,
            metadata={"login": url.rsplit("/", 1)[-1], "source_url": url, "repo_count": 3},
        )

    monkeypatch.setattr(linkedin_via_github, "fetch_github", fake_fetch_github)


@pytest.mark.asyncio
async def test_linkedin_add_with_github_match_enriches_candidate(
    api_client: AsyncClient, monkeypatch,
) -> None:
    """LinkedIn URL + a confident GitHub match → the background enricher
    populates skills/experience/score via the existing GitHub-pipeline."""
    fake_llm = FakeLLMClient(structured_responses=[
        ExtractedCandidate(
            full_name="Alice Doe",
            headline="ML Engineer",
            location="Berlin",
            skills=["Python", "PyTorch"],
        ),
        ScoreResult(
            score=72,
            rationale="strong python + ml signal",
            breakdown=[ScoreBreakdownItem(criterion="python", weight=1, score=8, rationale="ok")],
        ),
    ])
    app.dependency_overrides[get_llm] = lambda: fake_llm

    _patch_search_returns(monkeypatch, "https://github.com/alice")
    _patch_fetch_github(
        monkeypatch,
        text="Name: Alice Doe\nGitHub login: alice\nBio: ML engineer\nLocation: Berlin",
    )

    try:
        job = (await api_client.post(
            "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
        )).json()
        create = await api_client.post(
            f"/api/jobs/{job['id']}/candidates",
            json={
                "kind": "url",
                "url": "https://www.linkedin.com/in/alice-doe/",
                "name": "Alice Doe",
                "snippet": "ML Engineer · Berlin",
            },
        )
        assert create.status_code == 202
        app_id = create.json()["application_id"]

        # Background task runs after response; give it a brief window.
        for _ in range(20):
            detail = (await api_client.get(f"/api/applications/{app_id}")).json()
            if detail["stage"] != "extracting":
                break
            await asyncio.sleep(0.05)

        assert detail["stage"] == "scored", detail
        cand = (await api_client.get(f"/api/candidates/{detail['candidate_id']}")).json()
        # Name from extractor wins (matches our snippet pre-fill anyway).
        assert cand["full_name"] == "Alice Doe"
        assert "PyTorch" in cand["skills"]
        # LinkedIn source_url is preserved through the enrichment hop.
        assert "linkedin.com" in cand["source_url"]
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_linkedin_add_with_no_github_match_stays_awaiting_paste(
    api_client: AsyncClient, pg_dsn: str, monkeypatch,
) -> None:
    """No confident GitHub match → no extraction runs, candidate sits in
    EXTRACTING with awaiting_paste=True so the manual paste path still
    works as the completion route."""
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()
    captured = _patch_search_returns(monkeypatch, None)

    try:
        job = (await api_client.post(
            "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
        )).json()
        create = await api_client.post(
            f"/api/jobs/{job['id']}/candidates",
            json={
                "kind": "url",
                "url": "https://www.linkedin.com/in/bob-someone/",
                "name": "Bob Someone",
                "snippet": "Generic snippet",
            },
        )
        app_id = create.json()["application_id"]

        # The task fires but should be a no-op; give it a moment anyway.
        await asyncio.sleep(0.1)

        # Backdate created_at past the 90s grace window so awaiting_paste
        # actually reflects "manual paste needed" rather than the
        # transient "auto-extraction still in progress" state.
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        engine = create_async_engine(pg_dsn)
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE applications SET created_at = :ts WHERE id = :id"),
                {"ts": datetime.now(timezone.utc) - timedelta(seconds=120), "id": app_id},
            )
        await engine.dispose()

        detail = (await api_client.get(f"/api/applications/{app_id}")).json()
        assert detail["stage"] == "extracting"
        assert detail["awaiting_paste"] is True
        assert captured["asked_for"] == "Bob Someone"
    finally:
        app.dependency_overrides.pop(get_llm, None)
