"""Connect / status / disconnect for the LinkedIn cookie management
endpoints. Playwright is patched out — we only exercise the API surface
and the encrypted-storage round-trip."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from recruiter.api import sourcing as sourcing_api
from recruiter.crypto import settings_cipher
from recruiter.sourcing.linkedin_login import LoginResult


@pytest.mark.asyncio
async def test_status_starts_disconnected(api_client: AsyncClient) -> None:
    r = await api_client.get("/api/sourcing/linkedin/status")
    assert r.status_code == 200
    assert r.json() == {
        "connected": False, "set_at": None, "auto_reconnect_enabled": False,
    }


@pytest.mark.asyncio
async def test_connect_persists_encrypted_cookie(
    api_client: AsyncClient, pg_dsn: str, monkeypatch,
) -> None:
    async def fake_login(email: str, password: str, **_kw: Any) -> LoginResult:
        assert email == "u@example.com"
        assert password == "hunter2"  # ensure it's actually passed through
        return LoginResult(status="connected", li_at="AQED-test-cookie-value")

    monkeypatch.setattr(sourcing_api, "login_and_extract_cookie", fake_login)

    r = await api_client.post(
        "/api/sourcing/linkedin/connect",
        json={"email": "u@example.com", "password": "hunter2"},
    )
    body = r.json()
    assert r.status_code == 200, body
    assert body["status"] == "connected"
    assert body["set_at"] is not None

    # Status now reports connected.
    s = await api_client.get("/api/sourcing/linkedin/status")
    assert s.json()["connected"] is True

    # Stored value is encrypted (not the raw cookie). Read via the same
    # pg DSN the test fixture provisioned so we see the migrated schema.
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(pg_dsn)
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT linkedin_li_at_enc FROM settings LIMIT 1")
        )
        stored = result.scalar()
    await engine.dispose()
    assert stored is not None
    assert stored != "AQED-test-cookie-value", \
        "raw cookie must not be stored in plaintext"
    assert settings_cipher().decrypt(stored) == "AQED-test-cookie-value"


@pytest.mark.asyncio
async def test_connect_challenge_does_not_persist(
    api_client: AsyncClient, monkeypatch,
) -> None:
    async def fake_login(email: str, password: str, **_kw: Any) -> LoginResult:
        return LoginResult(
            status="challenge",
            reason="captcha presented",
        )

    monkeypatch.setattr(sourcing_api, "login_and_extract_cookie", fake_login)

    r = await api_client.post(
        "/api/sourcing/linkedin/connect",
        json={"email": "u@example.com", "password": "x"},
    )
    body = r.json()
    assert r.status_code == 200
    assert body["status"] == "challenge"
    assert "captcha" in (body.get("reason") or "")

    # Status still disconnected.
    s = await api_client.get("/api/sourcing/linkedin/status")
    assert s.json()["connected"] is False


@pytest.mark.asyncio
async def test_connect_failed_surfaces_reason(
    api_client: AsyncClient, monkeypatch,
) -> None:
    async def fake_login(*_a: Any, **_kw: Any) -> LoginResult:
        return LoginResult(status="failed", reason="login rejected — check your email/password")

    monkeypatch.setattr(sourcing_api, "login_and_extract_cookie", fake_login)

    r = await api_client.post(
        "/api/sourcing/linkedin/connect",
        json={"email": "u@example.com", "password": "x"},
    )
    body = r.json()
    assert body["status"] == "failed"
    assert "rejected" in (body.get("reason") or "")


@pytest.mark.asyncio
async def test_connect_cookie_with_valid_cookie_persists(
    api_client: AsyncClient, monkeypatch,
) -> None:
    """User pastes a cookie that validates successfully → stored
    encrypted, status flips to connected, no creds stored."""
    async def fake_validate(li_at: str, **_kw: Any) -> LoginResult:
        assert li_at == "AQED-pasted-cookie"
        return LoginResult(status="connected", li_at=li_at)

    monkeypatch.setattr(sourcing_api, "validate_cookie", fake_validate)

    r = await api_client.post(
        "/api/sourcing/linkedin/connect-cookie",
        json={"li_at": "AQED-pasted-cookie"},
    )
    body = r.json()
    assert r.status_code == 200, body
    assert body["status"] == "connected"

    s = await api_client.get("/api/sourcing/linkedin/status")
    assert s.json() == {
        "connected": True,
        "set_at": body["set_at"],
        "auto_reconnect_enabled": False,  # paste-cookie never stores creds
    }


@pytest.mark.asyncio
async def test_connect_cookie_rejected_cookie_does_not_persist(
    api_client: AsyncClient, monkeypatch,
) -> None:
    """Cookie that LinkedIn redirects to /login → endpoint surfaces the
    failure and persists nothing."""
    async def fake_validate(li_at: str, **_kw: Any) -> LoginResult:
        return LoginResult(
            status="failed",
            reason="cookie rejected by LinkedIn — paste a fresh one",
        )

    monkeypatch.setattr(sourcing_api, "validate_cookie", fake_validate)

    r = await api_client.post(
        "/api/sourcing/linkedin/connect-cookie",
        json={"li_at": "AQED-expired"},
    )
    body = r.json()
    assert body["status"] == "failed"
    assert "fresh" in (body.get("reason") or "")

    s = await api_client.get("/api/sourcing/linkedin/status")
    assert s.json()["connected"] is False


@pytest.mark.asyncio
async def test_connect_cookie_clears_prior_auto_reconnect_creds(
    api_client: AsyncClient, monkeypatch,
) -> None:
    """If the user previously connected with remember=True and then
    switches to the paste-cookie path, the stored creds get cleared —
    paste-cookie is an explicit 'I'm managing cookies manually' signal."""
    async def fake_login(*_a: Any, **_kw: Any) -> LoginResult:
        return LoginResult(status="connected", li_at="cookie-via-login")

    async def fake_validate(li_at: str, **_kw: Any) -> LoginResult:
        return LoginResult(status="connected", li_at=li_at)

    monkeypatch.setattr(sourcing_api, "login_and_extract_cookie", fake_login)
    monkeypatch.setattr(sourcing_api, "validate_cookie", fake_validate)

    # Step 1: connect with remember.
    await api_client.post(
        "/api/sourcing/linkedin/connect",
        json={"email": "u@example.com", "password": "p", "remember": True},
    )
    s1 = (await api_client.get("/api/sourcing/linkedin/status")).json()
    assert s1["auto_reconnect_enabled"] is True

    # Step 2: switch to paste-cookie.
    await api_client.post(
        "/api/sourcing/linkedin/connect-cookie",
        json={"li_at": "AQED-pasted"},
    )
    s2 = (await api_client.get("/api/sourcing/linkedin/status")).json()
    assert s2["connected"] is True
    assert s2["auto_reconnect_enabled"] is False  # stored creds were cleared


@pytest.mark.asyncio
async def test_connect_cookie_skip_validation_persists_blind(
    api_client: AsyncClient, monkeypatch,
) -> None:
    """skip_validation=True bypasses the Playwright /feed roundtrip."""
    called = []

    async def fake_validate(*_a: Any, **_kw: Any) -> LoginResult:
        called.append(True)
        return LoginResult(status="failed", reason="should not be called")

    monkeypatch.setattr(sourcing_api, "validate_cookie", fake_validate)

    r = await api_client.post(
        "/api/sourcing/linkedin/connect-cookie",
        json={"li_at": "AQED-trusted", "skip_validation": True},
    )
    assert r.json()["status"] == "connected"
    assert called == []  # validator was bypassed


@pytest.mark.asyncio
async def test_disconnect_clears_cookie(
    api_client: AsyncClient, monkeypatch,
) -> None:
    async def fake_login(*_a: Any, **_kw: Any) -> LoginResult:
        return LoginResult(status="connected", li_at="AQED-x")

    monkeypatch.setattr(sourcing_api, "login_and_extract_cookie", fake_login)
    await api_client.post(
        "/api/sourcing/linkedin/connect",
        json={"email": "u@example.com", "password": "x"},
    )
    assert (await api_client.get("/api/sourcing/linkedin/status")).json()["connected"] is True

    r = await api_client.post("/api/sourcing/linkedin/disconnect")
    assert r.status_code == 204
    assert (await api_client.get("/api/sourcing/linkedin/status")).json() == {
        "connected": False, "set_at": None, "auto_reconnect_enabled": False,
    }
