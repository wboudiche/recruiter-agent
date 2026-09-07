import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.deps import get_session, require_role, require_user
from recruiter.crypto import settings_cipher
from recruiter.models import Role, SettingsRow, User
from recruiter.schemas.settings import SettingsRead, SettingsUpdate, SmtpConfigInput

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_user)])


# Backwards-compat alias kept until external callers migrate to settings_cipher().
_cipher = settings_cipher


async def _load_or_create(session: AsyncSession) -> SettingsRow:
    row = (await session.execute(select(SettingsRow).where(SettingsRow.id == 1))).scalar_one_or_none()
    if row is None:
        row = SettingsRow(id=1, default_llm_provider="anthropic")
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


def _to_read(row: SettingsRow) -> SettingsRead:
    # Decrypt the SMTP blob to surface non-secret fields (host/port/user/
    # from_email/use_starttls) so the UI can pre-fill on next open. The
    # password is intentionally NOT included in the read shape.
    smtp_cfg = get_smtp_config(row)
    return SettingsRead(
        default_llm_provider=row.default_llm_provider,
        has_anthropic_api_key=bool(row.anthropic_api_key_enc),
        local_llm_url=row.local_llm_url,
        has_local_llm_api_key=bool(row.local_llm_api_key_enc),
        model_overrides=row.model_overrides or {},
        has_google_oauth_tokens=bool(row.google_oauth_tokens_enc),
        has_smtp_config=bool(row.smtp_config_enc),
        smtp_host=smtp_cfg.host if smtp_cfg else None,
        smtp_port=smtp_cfg.port if smtp_cfg else None,
        smtp_user=smtp_cfg.user if smtp_cfg else None,
        smtp_from_email=smtp_cfg.from_email if smtp_cfg else None,
        smtp_use_starttls=smtp_cfg.use_starttls if smtp_cfg else None,
        recruiter_name=row.recruiter_name,
        recruiter_email=row.recruiter_email,
        monthly_llm_spend_cap_usd=row.monthly_llm_spend_cap_usd,
        search_provider=row.search_provider,
        search_engine_id=row.search_engine_id,
        has_search_api_key=bool(row.search_api_key_enc),
        has_github_token=bool(row.github_token_enc),
        has_apify_api_key=bool(row.apify_api_key_enc),
        apify_actor_id=row.apify_actor_id,
        enrichment_enabled=row.enrichment_enabled,
        has_enrichment_twitter_api_key=bool(row.enrichment_twitter_api_key_enc),
        has_enrichment_youtube_api_key=bool(row.enrichment_youtube_api_key_enc),
        has_enrichment_stackexchange_key=bool(row.enrichment_stackexchange_key_enc),
        enrichment_sources=row.enrichment_sources or {},
    )


@router.get("", response_model=SettingsRead)
async def get_settings(session: AsyncSession = Depends(get_session)) -> SettingsRead:
    row = await _load_or_create(session)
    return _to_read(row)


def _apply_secret(row: SettingsRow, attr: str, value: str | None, cipher) -> None:
    """Write one encrypted credential, honouring three distinct states.

    None  -> the client omitted the field: leave whatever is stored alone, so
             saving unrelated settings never clobbers a key.
    ""    -> an explicit revoke: drop the credential entirely (NULL), the same
             end state `/linkedin/disconnect` produces for the LinkedIn cookie.
    other -> store it encrypted.

    Without the "" case a stored secret could only ever be overwritten, never
    removed — the UI omits blank fields — so a key you had decided to stop
    trusting was stuck in the database with no way out.
    """
    if value is None:
        return
    setattr(row, attr, cipher.encrypt(value) if value else None)


@router.put("", response_model=SettingsRead)
async def update_settings(
    payload: SettingsUpdate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(Role.ADMIN)),
) -> SettingsRead:
    row = await _load_or_create(session)
    cipher = _cipher()
    if payload.default_llm_provider is not None:
        row.default_llm_provider = payload.default_llm_provider
    _apply_secret(row, "anthropic_api_key_enc", payload.anthropic_api_key, cipher)
    if payload.local_llm_url is not None:
        row.local_llm_url = payload.local_llm_url
    _apply_secret(row, "local_llm_api_key_enc", payload.local_llm_api_key, cipher)
    if payload.model_overrides is not None:
        row.model_overrides = payload.model_overrides
    if payload.smtp_config is not None:
        # If the client omits/blank the password, retain whatever's already
        # stored. Lets the UI re-save SMTP host/port/user/from changes
        # without re-typing the password every time.
        smtp_payload = payload.smtp_config.model_dump()
        if not smtp_payload.get("password"):
            existing = get_smtp_config(row)
            if existing is None or not existing.password:
                raise HTTPException(
                    status_code=422,
                    detail="SMTP password is required on first configuration",
                )
            smtp_payload["password"] = existing.password
        row.smtp_config_enc = cipher.encrypt(json.dumps(smtp_payload))
    if payload.recruiter_name is not None:
        row.recruiter_name = payload.recruiter_name
    if payload.recruiter_email is not None:
        row.recruiter_email = payload.recruiter_email
    if payload.monthly_llm_spend_cap_usd is not None:
        row.monthly_llm_spend_cap_usd = payload.monthly_llm_spend_cap_usd
    if payload.search_provider is not None:
        row.search_provider = payload.search_provider
    _apply_secret(row, "search_api_key_enc", payload.search_api_key, cipher)
    if payload.search_engine_id is not None:
        row.search_engine_id = payload.search_engine_id
    _apply_secret(row, "github_token_enc", payload.github_token, cipher)
    _apply_secret(row, "apify_api_key_enc", payload.apify_api_key, cipher)
    if payload.apify_actor_id is not None:
        # Empty string → reset to NULL (caller falls back to default).
        row.apify_actor_id = payload.apify_actor_id.strip() or None
    if payload.enrichment_enabled is not None:
        row.enrichment_enabled = payload.enrichment_enabled
    _apply_secret(row, "enrichment_twitter_api_key_enc", payload.enrichment_twitter_api_key, cipher)
    _apply_secret(row, "enrichment_youtube_api_key_enc", payload.enrichment_youtube_api_key, cipher)
    _apply_secret(
        row, "enrichment_stackexchange_key_enc", payload.enrichment_stackexchange_key, cipher
    )
    if payload.enrichment_sources is not None:
        row.enrichment_sources = payload.enrichment_sources
    await session.commit()
    await session.refresh(row)
    return _to_read(row)


def get_smtp_config(row: SettingsRow) -> SmtpConfigInput | None:
    """Decrypt and parse the SMTP config blob from the Settings row."""
    if not row.smtp_config_enc:
        return None
    raw = _cipher().decrypt(row.smtp_config_enc)
    return SmtpConfigInput(**json.loads(raw))
