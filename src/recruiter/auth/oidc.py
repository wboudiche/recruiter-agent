import base64
import hashlib
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx
from authlib.jose import jwt
from authlib.jose.errors import JoseError


class OIDCError(Exception):
    """Base for OIDC client failures (network, parsing, etc.)."""


class OIDCValidationError(OIDCError):
    """id_token failed structural validation."""


@dataclass
class OIDCConfig:
    issuer: str
    client_id: str
    client_secret: str
    redirect_uri: str


def generate_pkce() -> tuple[str, str]:
    """Return (verifier, S256 challenge). RFC 7636."""
    verifier = secrets.token_urlsafe(64)[:96]  # 43..128 chars
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorize_url(
    cfg: OIDCConfig,
    *,
    authorize_endpoint: str,
    state: str,
    nonce: str,
    code_challenge: str,
    scope: str = "openid email profile",
    extra_params: dict[str, str] | None = None,
) -> str:
    params = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": cfg.redirect_uri,
        "scope": scope,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if extra_params:
        params.update(extra_params)
    return f"{authorize_endpoint}?{urllib.parse.urlencode(params)}"


class OIDCClient:
    """Thin OIDC client: discovery, code exchange, JWKS-validated id_token decode."""

    def __init__(self, cfg: OIDCConfig, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._cfg = cfg
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)
        self._discovery: dict[str, Any] | None = None
        self._jwks: dict[str, Any] | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def discover(self) -> dict[str, Any]:
        if self._discovery is not None:
            return self._discovery
        url = self._cfg.issuer.rstrip("/") + "/.well-known/openid-configuration"
        r = await self._client.get(url)
        r.raise_for_status()
        self._discovery = r.json()
        return self._discovery

    async def get_jwks(self) -> dict[str, Any]:
        if self._jwks is not None:
            return self._jwks
        d = await self.discover()
        r = await self._client.get(d["jwks_uri"])
        r.raise_for_status()
        self._jwks = r.json()
        return self._jwks

    async def exchange_code(self, *, code: str, code_verifier: str) -> dict[str, Any]:
        d = await self.discover()
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._cfg.redirect_uri,
            "client_id": self._cfg.client_id,
            "client_secret": self._cfg.client_secret,
            "code_verifier": code_verifier,
        }
        r = await self._client.post(
            d["token_endpoint"], data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if r.status_code >= 500:
            raise OIDCError(f"token endpoint {r.status_code}: {r.text[:200]}")
        if r.status_code != 200:
            raise OIDCValidationError(f"token endpoint {r.status_code}: {r.text[:200]}")
        return r.json()

    async def decode_id_token(self, id_token: str) -> dict[str, Any]:
        """Verify signature + return claims dict. Raises OIDCValidationError on failure."""
        jwks = await self.get_jwks()
        try:
            claims = jwt.decode(id_token, jwks)
            claims.validate()  # exp, iat, nbf
        except JoseError as e:
            raise OIDCValidationError(f"id_token signature/claims invalid: {e}") from e
        return dict(claims)


def validate_id_token_claims(
    claims: dict[str, Any],
    *,
    issuer: str,
    audience: str,
    expected_nonce: str,
) -> dict[str, Any]:
    """Structural checks beyond Authlib's signature verification.

    Returns a normalized user-info dict: {email, sub, name, picture}.
    Raises OIDCValidationError on any failure.
    """
    if claims.get("iss") != issuer:
        raise OIDCValidationError(f"id_token issuer mismatch: {claims.get('iss')!r}")
    aud = claims.get("aud")
    aud_ok = aud == audience or (isinstance(aud, list) and audience in aud)
    if not aud_ok:
        raise OIDCValidationError(f"id_token audience mismatch: {aud!r}")
    exp = claims.get("exp")
    if not exp or int(exp) < time.time():
        raise OIDCValidationError("id_token expired")
    if claims.get("nonce") != expected_nonce:
        raise OIDCValidationError("id_token nonce mismatch")
    # email_verified: explicitly False is rejected; absent is treated as verified
    # (Google omits the field for Workspace).
    if claims.get("email_verified") is False:
        raise OIDCValidationError("email not verified")
    email = claims.get("email")
    sub = claims.get("sub")
    if not email or not sub:
        raise OIDCValidationError("id_token missing email or sub")
    return {
        "email": email,
        "sub": sub,
        "name": claims.get("name"),
        "picture": claims.get("picture"),
    }
