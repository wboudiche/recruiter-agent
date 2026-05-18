import pytest
from httpx import AsyncClient

from recruiter.config import get_config


@pytest.fixture(autouse=True)
def _reset_config_and_limiter():
    # SlowAPI uses an in-memory storage by default; without a reset the
    # 5/min budget on /login/password is shared across tests and the
    # later cases trip 429 instead of exercising their assertions.
    from recruiter.api.rate_limit import limiter

    get_config.cache_clear()
    limiter.reset()
    yield
    limiter.reset()
    get_config.cache_clear()


@pytest.fixture
def password_env(monkeypatch):
    monkeypatch.setenv("RECRUITER_DEFAULT_ACCOUNT_EMAIL", "admin@acme.com")
    monkeypatch.setenv("RECRUITER_DEFAULT_ACCOUNT_PASSWORD", "s3cret-bootstrap")
    # dev_bypass and OIDC must be off for the password path to be the
    # only auth method in play.
    monkeypatch.setenv("RECRUITER_DEV_AUTH_BYPASS", "")
    monkeypatch.setenv("RECRUITER_OIDC_ISSUER", "")
    get_config.cache_clear()


@pytest.mark.asyncio
async def test_methods_reports_password_when_configured(
    api_client_unauth: AsyncClient, password_env,
) -> None:
    r = await api_client_unauth.get("/api/auth/methods")
    assert r.status_code == 200
    assert r.json() == {"oidc": False, "password": True}


@pytest.mark.asyncio
async def test_methods_reports_neither_when_unconfigured(
    api_client_unauth: AsyncClient,
) -> None:
    r = await api_client_unauth.get("/api/auth/methods")
    assert r.status_code == 200
    assert r.json() == {"oidc": False, "password": False}


@pytest.mark.asyncio
async def test_login_password_success_sets_cookie_and_upserts_user(
    api_client_unauth: AsyncClient, password_env,
) -> None:
    r = await api_client_unauth.post(
        "/api/auth/login/password",
        json={"email": "admin@acme.com", "password": "s3cret-bootstrap", "next": "/jobs"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["redirect"] == "/jobs"
    cookie = r.headers.get("set-cookie", "")
    assert "recruiter_session=" in cookie
    assert "HttpOnly" in cookie
    assert "samesite=strict" in cookie.lower()

    cookie_value = cookie.split(";")[0].split("=", 1)[1]
    me = await api_client_unauth.get(
        "/api/auth/me", cookies={"recruiter_session": cookie_value},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "admin@acme.com"


@pytest.mark.asyncio
async def test_login_password_email_is_normalized(
    api_client_unauth: AsyncClient, password_env,
) -> None:
    # Mixed case + surrounding whitespace must still match.
    r = await api_client_unauth.post(
        "/api/auth/login/password",
        json={"email": "  Admin@ACME.com  ", "password": "s3cret-bootstrap"},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_login_password_wrong_password_401(
    api_client_unauth: AsyncClient, password_env,
) -> None:
    r = await api_client_unauth.post(
        "/api/auth/login/password",
        json={"email": "admin@acme.com", "password": "wrong"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_password_wrong_email_401(
    api_client_unauth: AsyncClient, password_env,
) -> None:
    r = await api_client_unauth.post(
        "/api/auth/login/password",
        json={"email": "someone@else.com", "password": "s3cret-bootstrap"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_password_not_configured_returns_404(
    api_client_unauth: AsyncClient,
) -> None:
    r = await api_client_unauth.post(
        "/api/auth/login/password",
        json={"email": "admin@acme.com", "password": "anything"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_login_password_rate_limit_triggers(
    api_client_unauth: AsyncClient, password_env,
) -> None:
    # 5/minute → six identical wrong attempts: the sixth must be 429.
    for _ in range(5):
        r = await api_client_unauth.post(
            "/api/auth/login/password",
            json={"email": "admin@acme.com", "password": "wrong"},
        )
        assert r.status_code == 401
    r = await api_client_unauth.post(
        "/api/auth/login/password",
        json={"email": "admin@acme.com", "password": "wrong"},
    )
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_login_password_rejects_open_redirect(
    api_client_unauth: AsyncClient, password_env,
) -> None:
    r = await api_client_unauth.post(
        "/api/auth/login/password",
        json={
            "email": "admin@acme.com",
            "password": "s3cret-bootstrap",
            "next": "https://evil.tld/phish",
        },
    )
    assert r.status_code == 200
    assert r.json()["redirect"] == "/"
