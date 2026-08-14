"""Login moves from a single env pair to the users table. The env pair
survives as break-glass.

The three failure modes below MUST be indistinguishable. If unknown-email
and wrong-password differ in status, body, or (via the dummy verify) rough
timing, the login page becomes an account-enumeration oracle.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.auth.passwords import hash_password
from recruiter.config import get_config
from recruiter.models import Role, User


@pytest.fixture(autouse=True)
def _reset_limiter():
    # SlowAPI's in-memory storage persists across tests within a module;
    # without a reset, this module's own login attempts (several per test)
    # exhaust the 5/min budget on /login/password before later tests run,
    # and they'd 429 instead of exercising their actual assertions.
    from recruiter.api.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()
    get_config.cache_clear()


async def _add_user(
    session: AsyncSession, email: str, password: str | None = "pw",
    role: Role = Role.RECRUITER, is_active: bool = True,
) -> User:
    user = User(
        email=email, role=role, is_active=is_active,
        password_hash=hash_password(password) if password else None,
    )
    session.add(user)
    await session.commit()
    return user


@pytest.mark.asyncio
async def test_user_from_the_table_can_log_in(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    await _add_user(db_session_with_schema, "recruiter@acme.com", "s3cret")

    r = await api_client_unauth.post(
        "/api/auth/login/password",
        json={"email": "recruiter@acme.com", "password": "s3cret"},
    )

    assert r.status_code == 204
    assert "recruiter_session" in r.cookies


@pytest.mark.asyncio
async def test_wrong_password_unknown_email_and_deactivated_are_identical(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    await _add_user(db_session_with_schema, "real@acme.com", "s3cret")
    await _add_user(db_session_with_schema, "gone@acme.com", "s3cret", is_active=False)

    wrong = await api_client_unauth.post(
        "/api/auth/login/password",
        json={"email": "real@acme.com", "password": "nope"},
    )
    unknown = await api_client_unauth.post(
        "/api/auth/login/password",
        json={"email": "nobody@acme.com", "password": "nope"},
    )
    disabled = await api_client_unauth.post(
        "/api/auth/login/password",
        json={"email": "gone@acme.com", "password": "s3cret"},
    )

    assert wrong.status_code == unknown.status_code == disabled.status_code == 401
    assert wrong.json() == unknown.json() == disabled.json()


@pytest.mark.asyncio
async def test_oidc_user_without_a_password_cannot_use_the_form(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    await _add_user(db_session_with_schema, "sso@acme.com", password=None)

    r = await api_client_unauth.post(
        "/api/auth/login/password",
        json={"email": "sso@acme.com", "password": ""},
    )

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_deactivation_kills_an_existing_session_immediately(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    """Sessions last days. If deactivation only stopped NEW logins, a
    dismissed user would keep full access until their cookie expired."""
    user = await _add_user(db_session_with_schema, "temp@acme.com", "s3cret")
    await api_client_unauth.post(
        "/api/auth/login/password",
        json={"email": "temp@acme.com", "password": "s3cret"},
    )
    assert (await api_client_unauth.get("/api/auth/me")).status_code == 200

    user.is_active = False
    await db_session_with_schema.commit()

    assert (await api_client_unauth.get("/api/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_me_exposes_role_so_the_ui_can_render_itself(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    await _add_user(db_session_with_schema, "boss@acme.com", "s3cret", role=Role.ADMIN)
    await api_client_unauth.post(
        "/api/auth/login/password",
        json={"email": "boss@acme.com", "password": "s3cret"},
    )

    body = (await api_client_unauth.get("/api/auth/me")).json()

    assert body["role"] == "admin"
    # The docstring on UserRead forbids leaking IdP correlation keys.
    assert "sub" not in body and "issuer" not in body


@pytest.mark.asyncio
async def test_migration_promoted_admin_with_no_hash_still_logs_in_via_break_glass(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession, monkeypatch,
) -> None:
    """Carried finding from Task 1: the `users_roles` migration promotes a
    pre-existing row by email match (`role='admin', is_active=true`) but
    does NOT backfill `password_hash`, since it never had a hash column to
    backfill from. This reproduces that exact row shape — same
    (issuer="default", sub=f"default:{email}") identity the startup seeder
    in main.py uses — and confirms the break-glass env path still lets that
    operator in, even though the users-table verify_password path can't
    (NULL hash never verifies).
    """
    monkeypatch.setenv("RECRUITER_DEFAULT_ACCOUNT_EMAIL", "admin@acme.com")
    monkeypatch.setenv("RECRUITER_DEFAULT_ACCOUNT_PASSWORD", "s3cret-bootstrap")
    get_config.cache_clear()

    promoted = User(
        email="admin@acme.com", sub="default:admin@acme.com", issuer="default",
        name="Admin", role=Role.ADMIN, is_active=True, password_hash=None,
    )
    db_session_with_schema.add(promoted)
    await db_session_with_schema.commit()

    try:
        r = await api_client_unauth.post(
            "/api/auth/login/password",
            json={"email": "admin@acme.com", "password": "s3cret-bootstrap"},
        )
        assert r.status_code == 204
        assert "recruiter_session" in r.cookies

        me = (await api_client_unauth.get("/api/auth/me")).json()
        assert me["email"] == "admin@acme.com"
        assert me["role"] == "admin"
        # Resolved to the SAME row (by issuer/sub), not a duplicate.
        assert me["id"] == promoted.id
    finally:
        get_config.cache_clear()
