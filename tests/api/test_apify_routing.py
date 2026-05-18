"""Apify preference + fallback behaviour."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from httpx import AsyncClient

from recruiter.api import candidates as candidates_api
from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.pipeline.parsers.text import ParsedContent
from recruiter.schemas.extraction import (
    EducationItem, ExperienceItem, ExtractedCandidate,
    ScoreBreakdownItem, ScoreResult,
)
from recruiter.sourcing.apify import (
    ApifyError, _build_api_url, _render_profile_text,
)


# -------- pure rendering tests (no API) ----------------------------------

def test_build_api_url_substitutes_slash_with_tilde() -> None:
    assert _build_api_url("dev_fusion/linkedin-profile-scraper") == (
        "https://api.apify.com/v2/acts/dev_fusion~linkedin-profile-scraper"
        "/run-sync-get-dataset-items"
    )
    assert _build_api_url("apify/some-actor") == (
        "https://api.apify.com/v2/acts/apify~some-actor"
        "/run-sync-get-dataset-items"
    )


def test_render_profile_text_minimal() -> None:
    text = _render_profile_text({"fullName": "Alice", "headline": "ML Eng"})
    assert "Name: Alice" in text
    assert "Headline: ML Eng" in text


def test_render_profile_text_falls_back_to_first_last() -> None:
    text = _render_profile_text({"firstName": "Ada", "lastName": "Lovelace"})
    assert "Name: Ada Lovelace" in text


def test_render_profile_text_with_dict_shaped_fields() -> None:
    """supreme_coder returns company/title/dates as nested dicts where
    dev_fusion returned bare strings. The renderer must handle both
    shapes without crashing on AttributeError."""
    data = {
        "fullName": {"text": "Jane Doe"},  # dict-shaped name
        "headline": "Director of ML",        # plain string
        "experiences": [
            {
                "title": {"name": "VP Engineering"},
                "company": {"name": "Stripe", "url": "https://…"},
                "startDate": {"year": 2022, "month": 3},
                "endDate": None,
                "description": {"text": "Led infra team."},
                "location": {"text": "Remote"},
            },
        ],
        "educations": [
            {
                "school": {"name": "Stanford"},
                "degree": {"name": "PhD"},
                "fieldOfStudy": {"name": "CS"},
            },
        ],
        "skills": [{"name": "Python"}, {"name": "Go"}],
    }
    text = _render_profile_text(data)
    assert "Name: Jane Doe" in text
    assert "Headline: Director of ML" in text
    assert "VP Engineering · Stripe (2022-03 – present)" in text
    assert "Led infra team." in text
    assert "PhD · CS · Stanford" in text
    assert "Skills: Python, Go" in text


def test_render_profile_text_rich() -> None:
    data = {
        "fullName": "Marie Laval",
        "headline": "Senior Data Scientist",
        "addressWithCountry": "Paris, France",
        "summary": "Builds ML systems.",
        "experiences": [
            {
                "title": "Senior Data Scientist", "companyName": "Acme",
                "jobStartedOn": "2021-06", "jobEndedOn": None,
                "jobStillWorking": True,
                "jobDescription": "RAG systems.",
                "jobLocation": "Paris",
            },
            {
                "title": "Data Scientist", "companyName": "BetaCo",
                "jobStartedOn": "2018-01", "jobEndedOn": "2021-06",
                "jobDescription": "",
            },
        ],
        "educations": [
            {
                "school": "ENSAE", "degree": "MSc",
                "fieldOfStudy": "Stats", "endDate": "2018",
            },
        ],
        "skills": [
            {"name": "Python"},
            {"name": "PyTorch"},
            "SQL",  # mixed shape, must still work
        ],
    }
    text = _render_profile_text(data)
    assert "Name: Marie Laval" in text
    assert "Location: Paris, France" in text
    assert "Senior Data Scientist · Acme (2021-06 – present)" in text
    assert "RAG systems." in text
    assert "Data Scientist · BetaCo (2018-01 – 2021-06)" in text
    assert "MSc · Stats · ENSAE (2018)" in text
    assert "Skills: Python, PyTorch, SQL" in text


# -------- routing tests ---------------------------------------------------

async def _configure_apify_key(api_client: AsyncClient, key: str) -> None:
    r = await api_client.put("/api/settings", json={"apify_api_key": key})
    assert r.status_code == 200
    assert r.json()["has_apify_api_key"] is True


@pytest.mark.asyncio
async def test_configured_actor_id_is_passed_to_fetcher(
    api_client: AsyncClient, monkeypatch,
) -> None:
    """Custom apify_actor_id in settings → forwarded to the fetcher."""
    seen_actor: list[str] = []

    async def fake_apify(url: str, *, api_key: str, actor_id: str = "", **_kw: Any) -> ParsedContent:
        seen_actor.append(actor_id)
        return ParsedContent(
            text="Name: Alice\nHeadline: x",
            metadata={"source_url": url, "provider": "apify"},
        )

    monkeypatch.setattr(candidates_api, "fetch_profile_via_apify", fake_apify)

    fake_llm = FakeLLMClient(structured_responses=[
        ExtractedCandidate(full_name="Alice", skills=["x"]),
        ScoreResult(
            score=10, rationale="ok",
            breakdown=[ScoreBreakdownItem(criterion="x", weight=1, score=1, rationale="ok")],
        ),
    ])
    app.dependency_overrides[get_llm] = lambda: fake_llm

    try:
        await api_client.put("/api/settings", json={
            "apify_api_key": "tk", "apify_actor_id": "curious_coder/linkedin-profile-scraper",
        })
        job = (await api_client.post(
            "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
        )).json()
        await api_client.post(
            f"/api/jobs/{job['id']}/candidates",
            json={"kind": "url", "url": "https://www.linkedin.com/in/alice/"},
        )
        await asyncio.sleep(0.1)
        assert seen_actor == ["curious_coder/linkedin-profile-scraper"]
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_apify_reports_in_band_error_for_free_plan(monkeypatch) -> None:
    """The dev_fusion free-plan rejection (status 201 + {"error": "..."}
    in the body) is surfaced as an ApifyError, not silently treated as
    a successful no-data response."""
    import httpx
    from recruiter.sourcing.apify import fetch_profile_via_apify

    class MockResp:
        status_code = 201
        text = '[{"error": "Users on the free Apify plan…"}]'
        def json(self):
            return [{"error": "Users on the free Apify plan…"}]

    class MockClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def post(self, *a, **kw): return MockResp()

    monkeypatch.setattr(httpx, "AsyncClient", MockClient)

    with pytest.raises(ApifyError, match="free Apify plan"):
        await fetch_profile_via_apify(
            "https://www.linkedin.com/in/alice/",
            api_key="tk", actor_id="dev_fusion/linkedin-profile-scraper",
        )


@pytest.mark.asyncio
async def test_linkedin_add_prefers_apify_when_key_is_set(
    api_client: AsyncClient, monkeypatch,
) -> None:
    """Configured Apify token → fetcher used → returned text drives the
    LLM extractor → application scored. Playwright is NOT called."""
    apify_called: list[str] = []
    playwright_called: list[str] = []

    async def fake_apify(url: str, *, api_key: str, **_kw: Any) -> ParsedContent:
        apify_called.append(url)
        return ParsedContent(
            text="Name: Alice Doe\nHeadline: Senior Rust Eng\nExperience:\n- ...",
            metadata={"source_url": url, "provider": "apify"},
        )

    async def fake_playwright(url: str, *, li_at: str, **_kw: Any) -> ParsedContent:
        playwright_called.append(url)
        return ParsedContent(text="", metadata={"needs_paste": True})

    monkeypatch.setattr(candidates_api, "fetch_profile_via_apify", fake_apify)
    monkeypatch.setattr(candidates_api, "fetch_linkedin_playwright", fake_playwright)

    fake_llm = FakeLLMClient(structured_responses=[
        ExtractedCandidate(
            full_name="Alice Doe", headline="Senior Rust Eng",
            skills=["Rust"],
            experience=[ExperienceItem(
                title="Senior Eng", company="Acme",
                start="2021", end=None, description=None,
            )],
            education=[EducationItem(
                school="MIT", degree="BSc", field="CS",
                start=None, end="2018",
            )],
        ),
        ScoreResult(
            score=80, rationale="strong",
            breakdown=[ScoreBreakdownItem(criterion="rust", weight=1, score=8, rationale="ok")],
        ),
    ])
    app.dependency_overrides[get_llm] = lambda: fake_llm

    try:
        await _configure_apify_key(api_client, "test-token-abc")
        job = (await api_client.post(
            "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
        )).json()
        create = await api_client.post(
            f"/api/jobs/{job['id']}/candidates",
            json={
                "kind": "url",
                "url": "https://www.linkedin.com/in/alice/",
                "name": "Alice Doe",
                "snippet": "Senior Rust Eng",
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
        assert apify_called == ["https://www.linkedin.com/in/alice/"]
        assert playwright_called == []  # Playwright never called
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_linkedin_add_falls_back_to_playwright_on_apify_error(
    api_client: AsyncClient, monkeypatch,
) -> None:
    """Apify returns 402 (out of credits) → falls through to Playwright
    instead of stalling the user. Profile still gets extracted via the
    secondary path."""
    apify_called: list[str] = []
    playwright_called: list[str] = []

    async def fake_apify(url: str, *, api_key: str, **_kw: Any) -> ParsedContent:
        apify_called.append(url)
        raise ApifyError("apify: out of credits", status_code=402)

    async def fake_playwright(url: str, *, li_at: str, **_kw: Any) -> ParsedContent:
        playwright_called.append(url)
        return ParsedContent(
            text="Name: Bob Smith\nHeadline: SRE",
            metadata={"source_url": url, "scraper": "playwright"},
        )

    monkeypatch.setattr(candidates_api, "fetch_profile_via_apify", fake_apify)
    monkeypatch.setattr(candidates_api, "fetch_linkedin_playwright", fake_playwright)
    monkeypatch.setenv("RECRUITER_LINKEDIN_LI_AT", "fake-cookie")
    from recruiter.config import get_config
    get_config.cache_clear()

    fake_llm = FakeLLMClient(structured_responses=[
        ExtractedCandidate(full_name="Bob Smith", headline="SRE", skills=["k8s"]),
        ScoreResult(
            score=50, rationale="ok",
            breakdown=[ScoreBreakdownItem(criterion="k8s", weight=1, score=5, rationale="ok")],
        ),
    ])
    app.dependency_overrides[get_llm] = lambda: fake_llm

    try:
        await _configure_apify_key(api_client, "test-token-abc")
        job = (await api_client.post(
            "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
        )).json()
        create = await api_client.post(
            f"/api/jobs/{job['id']}/candidates",
            json={
                "kind": "url",
                "url": "https://www.linkedin.com/in/bob/",
                "name": "Bob Smith",
                "snippet": "SRE",
            },
        )
        app_id = create.json()["application_id"]

        for _ in range(30):
            detail = (await api_client.get(f"/api/applications/{app_id}")).json()
            if detail["stage"] != "extracting":
                break
            await asyncio.sleep(0.05)
        assert detail["stage"] == "scored", detail
        # Both paths fired: apify tried first, playwright picked up.
        assert apify_called == ["https://www.linkedin.com/in/bob/"]
        assert playwright_called == ["https://www.linkedin.com/in/bob/"]
    finally:
        app.dependency_overrides.pop(get_llm, None)
        get_config.cache_clear()


@pytest.mark.asyncio
async def test_no_key_means_playwright_only(
    api_client: AsyncClient, monkeypatch,
) -> None:
    """No Apify token configured → fetcher not even invoked."""
    apify_called: list[str] = []
    playwright_called: list[str] = []

    async def fake_apify(*_a: Any, **_kw: Any) -> ParsedContent:
        apify_called.append("called")
        return ParsedContent(text="", metadata={})

    async def fake_playwright(url: str, *, li_at: str, **_kw: Any) -> ParsedContent:
        playwright_called.append(url)
        return ParsedContent(
            text="Name: Carol",
            metadata={"source_url": url, "scraper": "playwright"},
        )

    monkeypatch.setattr(candidates_api, "fetch_profile_via_apify", fake_apify)
    monkeypatch.setattr(candidates_api, "fetch_linkedin_playwright", fake_playwright)
    monkeypatch.setenv("RECRUITER_LINKEDIN_LI_AT", "fake-cookie")
    from recruiter.config import get_config
    get_config.cache_clear()

    fake_llm = FakeLLMClient(structured_responses=[
        ExtractedCandidate(full_name="Carol", skills=["x"]),
        ScoreResult(
            score=10, rationale="ok",
            breakdown=[ScoreBreakdownItem(criterion="x", weight=1, score=1, rationale="ok")],
        ),
    ])
    app.dependency_overrides[get_llm] = lambda: fake_llm

    try:
        # NOTE: no _configure_apify_key call — leave the key blank.
        job = (await api_client.post(
            "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
        )).json()
        create = await api_client.post(
            f"/api/jobs/{job['id']}/candidates",
            json={"kind": "url", "url": "https://www.linkedin.com/in/carol/"},
        )
        app_id = create.json()["application_id"]

        for _ in range(30):
            detail = (await api_client.get(f"/api/applications/{app_id}")).json()
            if detail["stage"] != "extracting":
                break
            await asyncio.sleep(0.05)
        assert detail["stage"] == "scored"
        assert apify_called == []   # never called
        assert playwright_called == ["https://www.linkedin.com/in/carol/"]
    finally:
        app.dependency_overrides.pop(get_llm, None)
        get_config.cache_clear()
