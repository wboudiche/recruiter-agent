import base64
import json
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from recruiter.auth.oidc import (
    OIDCClient,
    OIDCConfig,
    build_authorize_url,
    generate_pkce,
)

DISCOVERY = {
    "issuer": "https://idp.example.com",
    "authorization_endpoint": "https://idp.example.com/authorize",
    "token_endpoint": "https://idp.example.com/token",
    "jwks_uri": "https://idp.example.com/jwks",
}


def _config(**overrides) -> OIDCConfig:
    return OIDCConfig(
        issuer=overrides.get("issuer", "https://idp.example.com"),
        client_id=overrides.get("client_id", "cid"),
        client_secret=overrides.get("client_secret", "csecret"),
        redirect_uri=overrides.get("redirect_uri", "http://localhost:8765/api/auth/callback"),
    )


def test_generate_pkce_returns_url_safe_pair() -> None:
    verifier, challenge = generate_pkce()
    assert 43 <= len(verifier) <= 128  # RFC 7636
    assert verifier.replace("-", "").replace("_", "").isalnum()
    # challenge = base64url(sha256(verifier)) — 43 chars
    assert len(challenge) == 43


def test_build_authorize_url_contains_required_params() -> None:
    cfg = _config()
    url = build_authorize_url(
        cfg, authorize_endpoint="https://idp.example.com/authorize",
        state="ST", nonce="NO", code_challenge="CC",
        scope="openid email profile", extra_params={"hd": "acme.com"},
    )
    assert url.startswith("https://idp.example.com/authorize?")
    assert "response_type=code" in url
    assert "client_id=cid" in url
    assert "state=ST" in url
    assert "nonce=NO" in url
    assert "code_challenge=CC" in url
    assert "code_challenge_method=S256" in url
    assert "scope=openid+email+profile" in url or "scope=openid%20email%20profile" in url
    assert "hd=acme.com" in url


@pytest.mark.asyncio
async def test_oidc_client_discovery_caches_well_known() -> None:
    calls = {"discovery": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            calls["discovery"] += 1
            return httpx.Response(200, json=DISCOVERY)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = OIDCClient(_config(), transport=transport)
    d1 = await client.discover()
    d2 = await client.discover()
    assert d1 == d2 == DISCOVERY
    assert calls["discovery"] == 1  # cached


@pytest.mark.asyncio
async def test_oidc_client_exchange_code_returns_tokens() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json=DISCOVERY)
        if request.url.path.endswith("/token"):
            captured["body"] = dict(request.url.params) if request.url.params else None
            captured["form"] = request.content.decode()
            return httpx.Response(200, json={
                "id_token": "fake.id.token", "access_token": "at-1", "token_type": "Bearer",
            })
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = OIDCClient(_config(), transport=transport)
    tokens = await client.exchange_code(code="auth-code", code_verifier="VER")
    assert tokens["id_token"] == "fake.id.token"
    assert "code=auth-code" in captured["form"]
    assert "code_verifier=VER" in captured["form"]
    assert "grant_type=authorization_code" in captured["form"]
    assert "client_secret=csecret" in captured["form"]  # don't drop the secret


@pytest.mark.asyncio
async def test_oidc_client_validate_id_token_extracts_claims() -> None:
    """We don't run real signature verification in tests — a separate
    helper validate_id_token_claims() does the structural checks given
    already-decoded claims; signature verification is delegated to Authlib
    via JWKS in production."""
    from recruiter.auth.oidc import validate_id_token_claims

    now = int(time.time())
    claims = {
        "iss": "https://idp.example.com",
        "aud": "cid",
        "exp": now + 600,
        "nonce": "expected-nonce",
        "email": "alice@acme.com",
        "email_verified": True,
        "sub": "g-12345",
        "name": "Alice",
    }
    user_info = validate_id_token_claims(
        claims, issuer="https://idp.example.com",
        audience="cid", expected_nonce="expected-nonce",
    )
    assert user_info["email"] == "alice@acme.com"
    assert user_info["sub"] == "g-12345"
    assert user_info["name"] == "Alice"


def test_validate_id_token_rejects_wrong_issuer() -> None:
    from recruiter.auth.oidc import OIDCValidationError, validate_id_token_claims

    now = int(time.time())
    claims = {"iss": "https://attacker.example.com", "aud": "cid", "exp": now + 600,
              "nonce": "n", "email": "x@x.com", "sub": "s"}
    with pytest.raises(OIDCValidationError, match="issuer"):
        validate_id_token_claims(claims, issuer="https://idp.example.com",
                                 audience="cid", expected_nonce="n")


def test_validate_id_token_rejects_wrong_audience() -> None:
    from recruiter.auth.oidc import OIDCValidationError, validate_id_token_claims

    now = int(time.time())
    claims = {"iss": "https://idp.example.com", "aud": "other-cid",
              "exp": now + 600, "nonce": "n", "email": "x@x.com", "sub": "s"}
    with pytest.raises(OIDCValidationError, match="audience"):
        validate_id_token_claims(claims, issuer="https://idp.example.com",
                                 audience="cid", expected_nonce="n")


def test_validate_id_token_rejects_expired() -> None:
    from recruiter.auth.oidc import OIDCValidationError, validate_id_token_claims

    now = int(time.time())
    claims = {"iss": "https://idp.example.com", "aud": "cid",
              "exp": now - 60, "nonce": "n", "email": "x@x.com", "sub": "s"}
    with pytest.raises(OIDCValidationError, match="expired"):
        validate_id_token_claims(claims, issuer="https://idp.example.com",
                                 audience="cid", expected_nonce="n")


def test_validate_id_token_rejects_wrong_nonce() -> None:
    from recruiter.auth.oidc import OIDCValidationError, validate_id_token_claims

    now = int(time.time())
    claims = {"iss": "https://idp.example.com", "aud": "cid", "exp": now + 600,
              "nonce": "wrong", "email": "x@x.com", "sub": "s"}
    with pytest.raises(OIDCValidationError, match="nonce"):
        validate_id_token_claims(claims, issuer="https://idp.example.com",
                                 audience="cid", expected_nonce="expected")


def test_validate_id_token_rejects_explicitly_unverified_email() -> None:
    from recruiter.auth.oidc import OIDCValidationError, validate_id_token_claims

    now = int(time.time())
    claims = {"iss": "https://idp.example.com", "aud": "cid", "exp": now + 600,
              "nonce": "n", "email": "x@x.com", "email_verified": False, "sub": "s"}
    with pytest.raises(OIDCValidationError, match="not verified"):
        validate_id_token_claims(claims, issuer="https://idp.example.com",
                                 audience="cid", expected_nonce="n")


def test_validate_id_token_treats_missing_email_verified_as_verified() -> None:
    from recruiter.auth.oidc import validate_id_token_claims

    now = int(time.time())
    claims = {"iss": "https://idp.example.com", "aud": "cid", "exp": now + 600,
              "nonce": "n", "email": "x@x.com", "sub": "s"}
    info = validate_id_token_claims(claims, issuer="https://idp.example.com",
                                    audience="cid", expected_nonce="n")
    assert info["email"] == "x@x.com"
