"""Routing behaviour for LinkedIn URLs with/without `li_at` cookie."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from httpx import AsyncClient

from recruiter.api import candidates as candidates_api
from recruiter.api.candidates import get_llm
from recruiter.config import get_config
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.pipeline.enrichers import linkedin_via_github
from recruiter.pipeline.fetchers import linkedin_playwright
from recruiter.pipeline.parsers.text import ParsedContent
from recruiter.schemas.extraction import (
    EducationItem,
    ExperienceItem,
    ExtractedCandidate,
    ScoreBreakdownItem,
    ScoreResult,
)


@pytest.mark.asyncio
async def test_fetcher_returns_needs_paste_when_no_cookie() -> None:
    """Sanity: passing an empty li_at short-circuits without calling out."""
    pc = await linkedin_playwright.fetch_linkedin_playwright(
        "https://www.linkedin.com/in/alice/", li_at="",
    )
    assert pc.text == ""
    assert pc.metadata["needs_paste"] is True
    assert pc.metadata["reason"] == "no li_at cookie configured"


@pytest.mark.asyncio
async def test_fetcher_rejects_non_linkedin_url() -> None:
    with pytest.raises(ValueError):
        await linkedin_playwright.fetch_linkedin_playwright(
            "https://github.com/karpathy", li_at="dummy",
        )


@pytest.mark.asyncio
async def test_add_candidate_handles_playwright_browser_error(
    api_client: AsyncClient, monkeypatch,
) -> None:
    """An ERR_TOO_MANY_REDIRECTS (or any non-Timeout Playwright error)
    inside the fetcher must NOT bubble up as a 500 on the candidate-add
    endpoint. The application should be created with empty text and
    fall through to the awaiting_paste / GitHub-fallback path."""
    from recruiter.api import candidates as candidates_api
    from recruiter.pipeline.parsers.text import ParsedContent

    # Stub the Playwright fetcher to return the same `_flag` shape we
    # produce on a browser error — that's the contract the handler
    # depends on.
    async def fake_fetch(url: str, *, li_at: str, **_kw: Any) -> ParsedContent:
        return ParsedContent(
            text="",
            metadata={
                "needs_paste": True,
                "reason": "browser error: Error",
                "source_url": url,
            },
        )

    monkeypatch.setenv("RECRUITER_LINKEDIN_LI_AT", "fake-cookie")
    from recruiter.config import get_config
    get_config.cache_clear()

    monkeypatch.setattr(candidates_api, "fetch_linkedin_playwright", fake_fetch)
    monkeypatch.setattr(
        candidates_api, "enrich_linkedin_candidate_via_github",
        lambda **_: None,  # no-op
    )

    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()
    try:
        job = (await api_client.post(
            "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
        )).json()
        create = await api_client.post(
            f"/api/jobs/{job['id']}/candidates",
            json={
                "kind": "url",
                "url": "https://www.linkedin.com/in/some-bad-url",
                "name": "Some Person",
                "snippet": "x",
            },
        )
        # The headline: NO 500, application is created cleanly.
        assert create.status_code == 202, create.text
    finally:
        app.dependency_overrides.pop(get_llm, None)
        get_config.cache_clear()


@pytest.mark.asyncio
async def test_linkedin_add_with_cookie_runs_full_pipeline(
    api_client: AsyncClient, monkeypatch,
) -> None:
    """li_at configured + playwright returns real text → run the normal
    extraction+score pipeline, NOT the GitHub-by-name fallback. Stage
    should land at `scored`."""

    monkeypatch.setenv("RECRUITER_LINKEDIN_LI_AT", "fake-cookie-value")
    get_config.cache_clear()

    async def fake_playwright_fetch(url: str, *, li_at: str, **_kw: Any) -> ParsedContent:
        return ParsedContent(
            text=(
                "Marie Laval — Senior Data Scientist at Acme\n"
                "Experience: Senior Data Scientist at Acme (2021-now); "
                "Data Scientist at BetaCo (2018-2021)\n"
                "Education: MSc Stats, ENSAE (2018)\n"
                "Skills: Python, PyTorch, SQL"
            ),
            metadata={"source_url": url, "scraper": "playwright"},
        )

    # Patch in BOTH places the symbol is bound (the module that defines
    # it AND the candidates handler module that imported it by name).
    monkeypatch.setattr(
        linkedin_playwright, "fetch_linkedin_playwright", fake_playwright_fetch,
    )
    monkeypatch.setattr(
        candidates_api, "fetch_linkedin_playwright", fake_playwright_fetch,
    )

    # Guard: the GitHub-by-name fallback must NOT fire on this path.
    enricher_calls: list[int] = []

    async def fake_enricher(*, application_id: int, **_kw: Any) -> None:
        enricher_calls.append(application_id)

    monkeypatch.setattr(
        candidates_api, "enrich_linkedin_candidate_via_github", fake_enricher,
    )

    fake_llm = FakeLLMClient(structured_responses=[
        ExtractedCandidate(
            full_name="Marie Laval",
            headline="Senior Data Scientist",
            location="Paris",
            skills=["Python", "PyTorch", "SQL"],
            experience=[
                ExperienceItem(
                    title="Senior Data Scientist", company="Acme",
                    start="2021", end=None, description=None,
                ),
            ],
            education=[
                EducationItem(school="ENSAE", degree="MSc", field="Stats",
                              start=None, end="2018"),
            ],
        ),
        ScoreResult(
            score=84, rationale="strong stats + ml signal",
            breakdown=[ScoreBreakdownItem(criterion="ml", weight=1, score=9, rationale="ok")],
        ),
    ])
    app.dependency_overrides[get_llm] = lambda: fake_llm

    try:
        job = (await api_client.post(
            "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
        )).json()
        create = await api_client.post(
            f"/api/jobs/{job['id']}/candidates",
            json={
                "kind": "url",
                "url": "https://www.linkedin.com/in/marie-laval/",
                "name": "Marie Laval",
                "snippet": "Senior Data Scientist",
            },
        )
        assert create.status_code == 202
        app_id = create.json()["application_id"]

        for _ in range(30):
            detail = (await api_client.get(f"/api/applications/{app_id}")).json()
            if detail["stage"] != "extracting":
                break
            await asyncio.sleep(0.05)

        assert detail["stage"] == "scored", detail
        assert enricher_calls == [], "GitHub fallback should not run when Playwright produced text"

        cand = (await api_client.get(f"/api/candidates/{detail['candidate_id']}")).json()
        assert cand["full_name"] == "Marie Laval"
        assert len(cand["experience"]) == 1
        assert len(cand["education"]) == 1
        # LinkedIn URL is preserved as the canonical source.
        assert "linkedin.com" in cand["source_url"]
    finally:
        app.dependency_overrides.pop(get_llm, None)
        get_config.cache_clear()


@pytest.mark.asyncio
async def test_linkedin_add_without_cookie_falls_back_to_github_enricher(
    api_client: AsyncClient, pg_dsn: str, monkeypatch,
) -> None:
    """No cookie → Playwright fetcher returns empty text → handler routes
    to the GitHub-by-name enricher. Stage stays at extracting (the
    enricher is itself a no-op when we patch it)."""
    monkeypatch.setenv("RECRUITER_LINKEDIN_LI_AT", "")
    get_config.cache_clear()

    enricher_calls: list[int] = []

    async def fake_enricher(*, application_id: int, **_kw: Any) -> None:
        enricher_calls.append(application_id)

    monkeypatch.setattr(
        candidates_api, "enrich_linkedin_candidate_via_github", fake_enricher,
    )

    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()
    try:
        job = (await api_client.post(
            "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
        )).json()
        create = await api_client.post(
            f"/api/jobs/{job['id']}/candidates",
            json={
                "kind": "url",
                "url": "https://www.linkedin.com/in/no-cookie/",
                "name": "Some One",
                "snippet": "Eng",
            },
        )
        app_id = create.json()["application_id"]

        await asyncio.sleep(0.1)  # enough for the background task to fire
        assert enricher_calls == [app_id]

        # Backdate past the 90s grace window so awaiting_paste reflects
        # "needs manual paste" rather than "auto-extraction in progress".
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
    finally:
        app.dependency_overrides.pop(get_llm, None)
        get_config.cache_clear()
