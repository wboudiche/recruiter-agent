import time
from urllib.parse import parse_qs, urlparse

import pytest
from authlib.jose import JsonWebKey, jwt
from httpx import AsyncClient

from recruiter.config import get_config


@pytest.fixture(autouse=True)
def _reset_config_and_oidc():
    get_config.cache_clear()
    yield
    get_config.cache_clear()


@pytest.fixture
def oidc_env(monkeypatch):
    """Configure OIDC against a fake IdP whose endpoints we control."""
    monkeypatch.setenv("RECRUITER_OIDC_ISSUER", "https://idp.example.com")
    monkeypatch.setenv("RECRUITER_OIDC_CLIENT_ID", "cid")
    monkeypatch.setenv("RECRUITER_OIDC_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("RECRUITER_OIDC_REDIRECT_URI", "http://test/api/auth/callback")
    monkeypatch.setenv("RECRUITER_OIDC_ALLOWED_DOMAINS", "acme.com")
    get_config.cache_clear()


@pytest.fixture
def fake_idp(monkeypatch):
    """Patch OIDCClient.discover/decode to return canned values; capture
    exchange_code's code+verifier."""
    from recruiter.auth import oidc as oidc_module

    captured: dict = {}
    rsa_key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
    pub_jwks = {"keys": [rsa_key.as_dict(is_private=False, alg="RS256", use="sig", kid="k1")]}

    def make_id_token(claims: dict) -> str:
        header = {"alg": "RS256", "kid": "k1"}
        return jwt.encode(header, claims, rsa_key).decode()

    captured["make_id_token"] = make_id_token

    discovery = {
        "issuer": "https://idp.example.com",
        "authorization_endpoint": "https://idp.example.com/authorize",
        "token_endpoint": "https://idp.example.com/token",
        "jwks_uri": "https://idp.example.com/jwks",
    }

    async def fake_discover(self):
        return discovery
    async def fake_jwks(self):
        return pub_jwks
    async def fake_exchange(self, *, code, code_verifier):
        captured["code"] = code
        captured["verifier"] = code_verifier
        return {"id_token": captured["next_id_token"], "access_token": "at"}

    monkeypatch.setattr(oidc_module.OIDCClient, "discover", fake_discover)
    monkeypatch.setattr(oidc_module.OIDCClient, "get_jwks", fake_jwks)
    monkeypatch.setattr(oidc_module.OIDCClient, "exchange_code", fake_exchange)
    return captured


@pytest.mark.asyncio
async def test_login_redirects_to_idp_authorize(
    api_client: AsyncClient, oidc_env, fake_idp,
) -> None:
    r = await api_client.get("/api/auth/login?next=/jobs", follow_redirects=False)
    assert r.status_code == 302
    location = r.headers["location"]
    assert location.startswith("https://idp.example.com/authorize?")
    qs = parse_qs(urlparse(location).query)
    assert qs["client_id"] == ["cid"]
    assert qs["response_type"] == ["code"]
    assert qs["code_challenge_method"] == ["S256"]
    assert "state" in qs and "nonce" in qs


@pytest.mark.asyncio
async def test_login_503_when_oidc_not_configured(api_client: AsyncClient, monkeypatch) -> None:
    monkeypatch.setenv("RECRUITER_OIDC_ISSUER", "")
    get_config.cache_clear()
    r = await api_client.get("/api/auth/login")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_callback_full_happy_path(
    api_client: AsyncClient, oidc_env, fake_idp,
) -> None:
    # Trigger /login to create the OAuthState row + capture state.
    redirect = await api_client.get("/api/auth/login?next=/jobs", follow_redirects=False)
    state = parse_qs(urlparse(redirect.headers["location"]).query)["state"][0]
    nonce = parse_qs(urlparse(redirect.headers["location"]).query)["nonce"][0]

    fake_idp["next_id_token"] = fake_idp["make_id_token"]({
        "iss": "https://idp.example.com", "aud": "cid", "exp": int(time.time()) + 600,
        "iat": int(time.time()), "nonce": nonce,
        "email": "alice@acme.com", "email_verified": True,
        "sub": "g-12345", "name": "Alice",
    })

    r = await api_client.get(
        f"/api/auth/callback?code=auth-code&state={state}",
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/jobs"
    assert "recruiter_session=" in r.headers.get("set-cookie", "")
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "samesite=strict" in cookie.lower()


@pytest.mark.asyncio
async def test_callback_400_when_state_unknown(api_client: AsyncClient, oidc_env, fake_idp) -> None:
    r = await api_client.get("/api/auth/callback?code=x&state=unknown")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_callback_403_when_email_not_in_allowlist(
    api_client: AsyncClient, oidc_env, fake_idp,
) -> None:
    redirect = await api_client.get("/api/auth/login?next=/jobs", follow_redirects=False)
    state = parse_qs(urlparse(redirect.headers["location"]).query)["state"][0]
    nonce = parse_qs(urlparse(redirect.headers["location"]).query)["nonce"][0]

    fake_idp["next_id_token"] = fake_idp["make_id_token"]({
        "iss": "https://idp.example.com", "aud": "cid", "exp": int(time.time()) + 600,
        "iat": int(time.time()), "nonce": nonce,
        "email": "intruder@evil.com", "email_verified": True, "sub": "g-99",
    })

    r = await api_client.get(f"/api/auth/callback?code=c&state={state}")
    assert r.status_code == 403
    assert "Not authorized" in r.text


@pytest.mark.asyncio
async def test_me_401_when_not_logged_in(api_client: AsyncClient) -> None:
    r = await api_client.get("/api/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_logout_without_cookie_is_204(api_client: AsyncClient) -> None:
    """Idempotent: POST /logout without a cookie still returns 204
    (defends against double-clicks / stale-tab requests)."""
    r = await api_client.post("/api/auth/logout")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_logout_then_me_is_401(
    api_client: AsyncClient, oidc_env, fake_idp,
) -> None:
    """Login flow → /me works → /logout → /me 401."""
    redirect = await api_client.get("/api/auth/login?next=/jobs", follow_redirects=False)
    state = parse_qs(urlparse(redirect.headers["location"]).query)["state"][0]
    nonce = parse_qs(urlparse(redirect.headers["location"]).query)["nonce"][0]
    fake_idp["next_id_token"] = fake_idp["make_id_token"]({
        "iss": "https://idp.example.com", "aud": "cid", "exp": int(time.time()) + 600,
        "iat": int(time.time()), "nonce": nonce,
        "email": "alice@acme.com", "email_verified": True, "sub": "g-1", "name": "Alice",
    })
    cb = await api_client.get(f"/api/auth/callback?code=c&state={state}", follow_redirects=False)
    set_cookie = cb.headers["set-cookie"]
    cookie_value = set_cookie.split(";")[0].split("=", 1)[1]

    me = await api_client.get("/api/auth/me", cookies={"recruiter_session": cookie_value})
    assert me.status_code == 200
    assert me.json()["email"] == "alice@acme.com"

    out = await api_client.post("/api/auth/logout", cookies={"recruiter_session": cookie_value})
    assert out.status_code == 204

    me_again = await api_client.get("/api/auth/me", cookies={"recruiter_session": cookie_value})
    assert me_again.status_code == 401
