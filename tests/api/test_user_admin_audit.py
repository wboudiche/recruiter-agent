"""Privilege changes must leave a trace, and the password-change endpoint
must be as rate-limited as login.

`event_logs` cannot carry these: its FK is `application_id`, so it models
application events only. Until that changes, the application log is the
only record of who promoted, demoted, deactivated, or reset whom — in a
tool where role is what gates access to stored API keys and cookies.
"""

import logging

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.auth.passwords import hash_password
from recruiter.config import get_config
from recruiter.models import Role, User


@pytest.fixture(autouse=True)
def _reset_limiter():
    # SlowAPI's in-memory storage persists across tests within a module;
    # without a reset, this module's own logins exhaust the 5/min budget
    # and later tests 429 instead of exercising their assertions.
    from recruiter.api.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()
    get_config.cache_clear()


async def _add(
    session: AsyncSession, email: str, role: Role, password: str = "pw-12345",
    is_active: bool = True,
) -> User:
    user = User(
        email=email, role=role, is_active=is_active,
        password_hash=hash_password(password),
    )
    session.add(user)
    await session.commit()
    return user


async def _login(client: AsyncClient, email: str, password: str) -> None:
    r = await client.post(
        "/api/auth/login/password", json={"email": email, "password": password},
    )
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_role_change_is_logged_with_actor_and_target(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession, caplog,
) -> None:
    """Two admins, one demotes the other, then denies it. Without a log
    line naming both parties there is no way to establish what happened."""
    actor = await _add(db_session_with_schema, "boss@acme.com", Role.ADMIN, "s3cret-pw")
    target = await _add(db_session_with_schema, "other@acme.com", Role.ADMIN)
    await _login(api_client_unauth, "boss@acme.com", "s3cret-pw")

    with caplog.at_level(logging.INFO, logger="recruiter.api.users"):
        r = await api_client_unauth.patch(
            f"/api/users/{target.id}", json={"role": "viewer"},
        )

    assert r.status_code == 200
    logged = " ".join(rec.getMessage() for rec in caplog.records)
    assert str(actor.id) in logged
    assert str(target.id) in logged
    assert "viewer" in logged


@pytest.mark.asyncio
async def test_deactivation_and_password_reset_are_logged(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession, caplog,
) -> None:
    await _add(db_session_with_schema, "boss2@acme.com", Role.ADMIN, "s3cret-pw")
    target = await _add(db_session_with_schema, "victim@acme.com", Role.RECRUITER)
    await _login(api_client_unauth, "boss2@acme.com", "s3cret-pw")

    with caplog.at_level(logging.INFO, logger="recruiter.api.users"):
        await api_client_unauth.post(
            f"/api/users/{target.id}/password", json={"password": "brand-new-pw"},
        )
        await api_client_unauth.patch(
            f"/api/users/{target.id}", json={"is_active": False},
        )

    logged = " ".join(rec.getMessage() for rec in caplog.records)
    assert "password reset" in logged.lower()
    assert "deactivated" in logged.lower()


@pytest.mark.asyncio
async def test_user_creation_is_logged(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession, caplog,
) -> None:
    await _add(db_session_with_schema, "boss3@acme.com", Role.ADMIN, "s3cret-pw")
    await _login(api_client_unauth, "boss3@acme.com", "s3cret-pw")

    with caplog.at_level(logging.INFO, logger="recruiter.api.users"):
        r = await api_client_unauth.post("/api/users", json={
            "email": "fresh@acme.com", "role": "admin", "password": "initial-pw",
        })

    assert r.status_code == 201
    logged = " ".join(rec.getMessage() for rec in caplog.records)
    assert "fresh@acme.com" in logged
    assert "admin" in logged


@pytest.mark.asyncio
async def test_break_glass_warns_when_it_reactivates_or_repromotes(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
    caplog, monkeypatch,
) -> None:
    """Break-glass permanently restores the row to active admin. An
    operator who deliberately demoted that account and forgot to clear the
    env pair would otherwise have that decision reversed invisibly."""
    monkeypatch.setenv("RECRUITER_DEFAULT_ACCOUNT_EMAIL", "glass@acme.com")
    monkeypatch.setenv("RECRUITER_DEFAULT_ACCOUNT_PASSWORD", "break-glass-pw")
    get_config.cache_clear()

    # Deliberately demoted AND deactivated, exactly the state an operator
    # would leave behind while hardening.
    await _add(
        db_session_with_schema, "glass@acme.com", Role.VIEWER,
        password="unused-pw", is_active=False,
    )

    with caplog.at_level(logging.WARNING, logger="recruiter.api.auth"):
        r = await api_client_unauth.post(
            "/api/auth/login/password",
            json={"email": "glass@acme.com", "password": "break-glass-pw"},
        )

    assert r.status_code == 204
    warnings = [rec for rec in caplog.records if rec.levelno >= logging.WARNING]
    assert warnings, "break-glass privilege restoration must be logged at WARNING"
    logged = " ".join(rec.getMessage() for rec in warnings)
    assert "break-glass" in logged.lower()


@pytest.mark.asyncio
async def test_break_glass_stays_quiet_when_nothing_was_restored(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
    caplog, monkeypatch,
) -> None:
    """A WARNING on every ordinary break-glass login would train the
    operator to ignore it. Only an actual privilege change is noteworthy."""
    monkeypatch.setenv("RECRUITER_DEFAULT_ACCOUNT_EMAIL", "glass2@acme.com")
    monkeypatch.setenv("RECRUITER_DEFAULT_ACCOUNT_PASSWORD", "break-glass-pw")
    get_config.cache_clear()
    await _add(db_session_with_schema, "glass2@acme.com", Role.ADMIN, password="unused-pw")

    with caplog.at_level(logging.WARNING, logger="recruiter.api.auth"):
        r = await api_client_unauth.post(
            "/api/auth/login/password",
            json={"email": "glass2@acme.com", "password": "break-glass-pw"},
        )

    assert r.status_code == 204
    assert [rec for rec in caplog.records if rec.levelno >= logging.WARNING] == []


@pytest.mark.asyncio
async def test_self_service_password_change_is_rate_limited(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    """Login is capped at 5/minute; this endpoint verifies `current_password`
    too, so an attacker holding a stolen cookie could otherwise brute-force
    it at full speed and lock the real user out by changing it."""
    await _add(db_session_with_schema, "self@acme.com", Role.VIEWER, "old-pw-123")
    await _login(api_client_unauth, "self@acme.com", "old-pw-123")

    statuses = []
    for _ in range(7):
        r = await api_client_unauth.post("/api/auth/password", json={
            "current_password": "wrong-guess", "new_password": "irrelevant-pw",
        })
        statuses.append(r.status_code)

    assert 429 in statuses, f"expected a rate limit within 7 attempts, got {statuses}"
