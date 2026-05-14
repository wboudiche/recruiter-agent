import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.deps import get_session, require_user
from recruiter.auth.allowlist import is_email_allowed, parse_allowed_domains
from recruiter.auth.oidc import (
    OIDCClient,
    OIDCConfig,
    OIDCValidationError,
    build_authorize_url,
    generate_pkce,
    validate_id_token_claims,
)
from recruiter.auth.sessions import create_session, revoke_session
from recruiter.config import get_config
from recruiter.models import OAuthState, User
from recruiter.schemas.auth import UserRead

router = APIRouter(prefix="/api/auth", tags=["auth"])

def _safe_next(value: str | None) -> str:
    """Restrict post-login redirect targets to same-origin paths.

    Rejects absolute URLs (`https://evil.tld/...`), protocol-relative URLs
    (`//evil.tld`), Windows path traversal (`/\\evil`), header-injection
    payloads (`\\r\\n`), and anything containing a scheme delimiter
    (`javascript:`, `data:`). Falls back to `/`.
    """
    if not value or not isinstance(value, str):
        return "/"
    if "\r" in value or "\n" in value:
        return "/"
    if not value.startswith("/"):
        return "/"
    if value.startswith("//") or value.startswith("/\\"):
        return "/"
    if ":" in value:
        return "/"
    return value


_NOT_AUTHORIZED_HTML = """\
<!doctype html><meta charset="utf-8"><title>Not authorized</title>
<style>body{font-family:system-ui;max-width:480px;margin:4em auto;padding:1em}</style>
<h1>Not authorized</h1>
<p>Your account isn't authorized for this deployment. Please contact your admin.</p>
"""


def _oidc_config() -> OIDCConfig:
    cfg = get_config()
    return OIDCConfig(
        issuer=cfg.oidc_issuer,
        client_id=cfg.oidc_client_id,
        client_secret=cfg.oidc_client_secret,
        redirect_uri=cfg.oidc_redirect_uri,
    )


@router.get("/login")
async def login(
    next: str = "/",
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    cfg = get_config()
    if not cfg.oidc_issuer:
        raise HTTPException(status_code=503, detail="OIDC not configured")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier, challenge = generate_pkce()

    session.add(OAuthState(
        state=state, nonce=nonce, pkce_verifier=verifier, next_url=_safe_next(next),
    ))
    await session.commit()

    client = OIDCClient(_oidc_config())
    try:
        d = await client.discover()
    finally:
        await client.aclose()
    extra: dict[str, str] = {}
    domains = parse_allowed_domains(cfg.oidc_allowed_domains)
    if len(domains) == 1:
        extra["hd"] = domains[0]  # Google Workspace hint
    url = build_authorize_url(
        _oidc_config(), authorize_endpoint=d["authorization_endpoint"],
        state=state, nonce=nonce, code_challenge=challenge, extra_params=extra,
    )
    return RedirectResponse(url, status_code=302)


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> Response:
    cfg = get_config()
    if not cfg.oidc_issuer:
        raise HTTPException(status_code=503, detail="OIDC not configured")
    if not code or not state:
        raise HTTPException(status_code=400, detail="missing code or state")

    state_row = await session.get(OAuthState, state)
    if state_row is None:
        raise HTTPException(status_code=400, detail="invalid login state")
    age_seconds = (datetime.now(timezone.utc) - state_row.created_at).total_seconds()
    if age_seconds > 600:
        await session.delete(state_row)
        await session.commit()
        raise HTTPException(status_code=400, detail="login session expired, please retry")

    nonce = state_row.nonce
    verifier = state_row.pkce_verifier
    next_url = state_row.next_url
    await session.delete(state_row)
    await session.commit()

    client = OIDCClient(_oidc_config())
    try:
        tokens = await client.exchange_code(code=code, code_verifier=verifier)
        claims = await client.decode_id_token(tokens["id_token"])
    except OIDCValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        await client.aclose()

    try:
        info = validate_id_token_claims(
            claims, issuer=cfg.oidc_issuer, audience=cfg.oidc_client_id,
            expected_nonce=nonce,
        )
    except OIDCValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    domains = parse_allowed_domains(cfg.oidc_allowed_domains)
    if not is_email_allowed(info["email"], domains):
        return HTMLResponse(_NOT_AUTHORIZED_HTML, status_code=403)

    # Upsert user by (issuer, sub).
    user = (await session.execute(
        select(User)
        .where(User.issuer == cfg.oidc_issuer)
        .where(User.sub == info["sub"])
    )).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if user is None:
        user = User(
            email=info["email"], sub=info["sub"], issuer=cfg.oidc_issuer,
            name=info.get("name"), picture=info.get("picture"), last_login_at=now,
        )
        session.add(user)
    else:
        user.email = info["email"]
        user.name = info.get("name")
        user.picture = info.get("picture")
        user.last_login_at = now
    await session.commit()

    token = await create_session(
        session, user_id=user.id, ttl_days=cfg.session_ttl_days,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )

    response = RedirectResponse(_safe_next(next_url), status_code=302)
    response.set_cookie(
        key="recruiter_session", value=token, httponly=True, samesite="strict",
        secure=cfg.secure_cookies, max_age=cfg.session_ttl_days * 86400, path="/",
    )
    return response


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> Response:
    cookie = request.cookies.get("recruiter_session")
    if cookie:
        await revoke_session(session, token=cookie)
    # Mirror set_cookie's attributes so the unset matches in all browsers.
    cfg = get_config()
    response.delete_cookie(
        key="recruiter_session", path="/",
        httponly=True, samesite="strict", secure=cfg.secure_cookies,
    )
    return Response(status_code=204)


@router.get("/me", response_model=UserRead)
async def me(user: User = Depends(require_user)) -> UserRead:
    return UserRead.model_validate(user)
