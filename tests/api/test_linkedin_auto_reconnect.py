"""Auto-reconnect: expired cookie → re-login with stored creds → retry fetch.

Playwright is patched at both call sites (login flow + profile fetcher)
so tests don't touch the network."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from httpx import AsyncClient

from recruiter.api import candidates as candidates_api
from recruiter.api import sourcing as sourcing_api
from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.pipeline.parsers.text import ParsedContent
from recruiter.schemas.extraction import (
    ExtractedCandidate, ScoreBreakdownItem, ScoreResult,
)
from recruiter.sourcing.linkedin_login import LoginResult


async def _connect(api_client: AsyncClient, *, remember: bool) -> None:
    """Helper: enroll the test as 'connected' via the API."""
    r = await api_client.post(
        "/api/sourcing/linkedin/connect",
        json={
            "email": "u@example.com", "password": "hunter2", "remember": remember,
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "connected"


@pytest.mark.asyncio
async def test_expired_cookie_with_stored_creds_reconnects_and_retries(
    api_client: AsyncClient, monkeypatch,
) -> None:
    """The headline case: cookie expired → auto-reconnect fires → second
    fetch succeeds → the application transitions through the normal
    Extracting → Scored pipeline."""

    # First login (during /connect) and the auto-reconnect login both
    # succeed. We hand out distinct cookies to verify the new one is used.
    login_calls: list[str] = []

    async def fake_login(email: str, password: str, **_kw: Any) -> LoginResult:
        login_calls.append(password)
        return LoginResult(
            status="connected",
            li_at=f"cookie-{len(login_calls)}",  # cookie-1, cookie-2
        )

    monkeypatch.setattr(sourcing_api, "login_and_extract_cookie", fake_login)
    monkeypatch.setattr(candidates_api, "login_and_extract_cookie", fake_login)

    # Playwright fetch: first call returns expired-cookie failure, the
    # retry returns real profile text.
    fetch_seq: list[str] = []

    async def fake_fetch(url: str, *, li_at: str, **_kw: Any) -> ParsedContent:
        fetch_seq.append(li_at)
        if li_at == "cookie-1":
            return ParsedContent(
                text="", metadata={
                    "needs_paste": True,
                    "reason": "cookie expired or challenged",
                    "source_url": url,
                },
            )
        return ParsedContent(
            text="Alice Doe\nSenior Rust Engineer\nExperience: …",
            metadata={"source_url": url, "scraper": "playwright"},
        )

    monkeypatch.setattr(candidates_api, "fetch_linkedin_playwright", fake_fetch)

    fake_llm = FakeLLMClient(structured_responses=[
        ExtractedCandidate(full_name="Alice Doe", headline="Senior Rust Engineer", skills=["Rust"]),
        ScoreResult(
            score=80, rationale="ok",
            breakdown=[ScoreBreakdownItem(criterion="rust", weight=1, score=8, rationale="ok")],
        ),
    ])
    app.dependency_overrides[get_llm] = lambda: fake_llm

    try:
        await _connect(api_client, remember=True)

        job_id = (await api_client.post(
            "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
        )).json()["id"]

        create = await api_client.post(
            f"/api/jobs/{job_id}/candidates",
            json={
                "kind": "url",
                "url": "https://www.linkedin.com/in/alice/",
                "name": "Alice Doe",
                "snippet": "Senior Rust Engineer",
            },
        )
        assert create.status_code == 202
        app_id = create.json()["application_id"]

        # Background pipeline should drive it to scored.
        for _ in range(30):
            detail = (await api_client.get(f"/api/applications/{app_id}")).json()
            if detail["stage"] != "extracting":
                break
            await asyncio.sleep(0.05)

        assert detail["stage"] == "scored", detail
        # Sequence: initial /connect login (cookie-1) +
        # auto-reconnect login (cookie-2). Fetcher saw both cookies.
        assert login_calls == ["hunter2", "hunter2"]
        assert fetch_seq == ["cookie-1", "cookie-2"]
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_expired_cookie_without_stored_creds_does_not_reconnect(
    api_client: AsyncClient, monkeypatch,
) -> None:
    """User connected WITHOUT 'remember' → cookie expired → no auto-
    reconnect → fall through to today's awaiting_paste path. The user
    will manually reconnect."""

    async def fake_login(*_a: Any, **_kw: Any) -> LoginResult:
        return LoginResult(status="connected", li_at="cookie-1")

    monkeypatch.setattr(sourcing_api, "login_and_extract_cookie", fake_login)
    reconnect_attempted = []

    async def fail_login(*_a: Any, **_kw: Any) -> LoginResult:
        reconnect_attempted.append(True)
        return LoginResult(status="failed", reason="should not be called")

    monkeypatch.setattr(candidates_api, "login_and_extract_cookie", fail_login)

    async def fake_fetch(url: str, *, li_at: str, **_kw: Any) -> ParsedContent:
        return ParsedContent(
            text="", metadata={
                "needs_paste": True,
                "reason": "cookie expired or challenged",
                "source_url": url,
            },
        )

    monkeypatch.setattr(candidates_api, "fetch_linkedin_playwright", fake_fetch)
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()

    try:
        await _connect(api_client, remember=False)
        job_id = (await api_client.post(
            "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
        )).json()["id"]
        create = await api_client.post(
            f"/api/jobs/{job_id}/candidates",
            json={
                "kind": "url",
                "url": "https://www.linkedin.com/in/bob/",
                "name": "Bob",
                "snippet": "x",
            },
        )
        assert create.status_code == 202

        await asyncio.sleep(0.1)
        # No auto-reconnect login was attempted because remember=False
        # means no stored creds.
        assert reconnect_attempted == []
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_auto_reconnect_login_challenge_clears_cookie(
    api_client: AsyncClient, monkeypatch,
) -> None:
    """If LinkedIn challenges the auto-reconnect login (captcha / MFA),
    we clear the stored cookie so the UI prompts the user to manually
    reconnect from their normal browser."""

    async def first_login_ok(*_a: Any, **_kw: Any) -> LoginResult:
        return LoginResult(status="connected", li_at="cookie-1")

    monkeypatch.setattr(sourcing_api, "login_and_extract_cookie", first_login_ok)

    async def reconnect_challenge(*_a: Any, **_kw: Any) -> LoginResult:
        return LoginResult(status="challenge", reason="captcha presented")

    monkeypatch.setattr(candidates_api, "login_and_extract_cookie", reconnect_challenge)

    async def expired_fetch(url: str, *, li_at: str, **_kw: Any) -> ParsedContent:
        return ParsedContent(
            text="", metadata={
                "needs_paste": True,
                "reason": "cookie expired or challenged",
                "source_url": url,
            },
        )

    monkeypatch.setattr(candidates_api, "fetch_linkedin_playwright", expired_fetch)
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()

    try:
        await _connect(api_client, remember=True)
        # Status: connected with auto-reconnect.
        s1 = (await api_client.get("/api/sourcing/linkedin/status")).json()
        assert s1["connected"] is True
        assert s1["auto_reconnect_enabled"] is True

        job_id = (await api_client.post(
            "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
        )).json()["id"]
        await api_client.post(
            f"/api/jobs/{job_id}/candidates",
            json={
                "kind": "url",
                "url": "https://www.linkedin.com/in/charlie/",
                "name": "Charlie",
                "snippet": "x",
            },
        )
        await asyncio.sleep(0.1)

        # Cookie is cleared (challenge requires user intervention) but
        # the stored creds are preserved — the user may just need to
        # clear a one-off check in their normal browser, after which
        # auto-reconnect will work again.
        s2 = (await api_client.get("/api/sourcing/linkedin/status")).json()
        assert s2["connected"] is False
        assert s2["auto_reconnect_enabled"] is True  # creds still there
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_disconnect_clears_stored_creds_too(
    api_client: AsyncClient, monkeypatch,
) -> None:
    async def fake_login(*_a: Any, **_kw: Any) -> LoginResult:
        return LoginResult(status="connected", li_at="cookie-1")

    monkeypatch.setattr(sourcing_api, "login_and_extract_cookie", fake_login)

    await _connect(api_client, remember=True)
    s_before = (await api_client.get("/api/sourcing/linkedin/status")).json()
    assert s_before["auto_reconnect_enabled"] is True

    r = await api_client.post("/api/sourcing/linkedin/disconnect")
    assert r.status_code == 204
    s_after = (await api_client.get("/api/sourcing/linkedin/status")).json()
    assert s_after == {
        "connected": False, "set_at": None, "auto_reconnect_enabled": False,
    }
