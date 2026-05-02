import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.deps import get_session, require_user
from recruiter.config import get_config
from recruiter.crypto import SecretCipher
from recruiter.models import SettingsRow
from recruiter.schemas.settings import SettingsRead, SettingsUpdate, SmtpConfigInput

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_user)])


def _cipher() -> SecretCipher:
    raw = get_config().settings_key
    # Accept either a 32-byte raw string or a 64-char hex-encoded string. No silent padding.
    if len(raw) == 64:
        try:
            key = bytes.fromhex(raw)
        except ValueError as exc:
            raise RuntimeError("RECRUITER_SETTINGS_KEY: 64-char value must be valid hex") from exc
    else:
        key = raw.encode("utf-8")
    if len(key) != 32:
        raise RuntimeError(
            "RECRUITER_SETTINGS_KEY must be 32 bytes (or 64 hex chars). "
            "Generate with: python -c 'import secrets; print(secrets.token_hex(32))'"
        )
    return SecretCipher(key)


async def _load_or_create(session: AsyncSession) -> SettingsRow:
    row = (await session.execute(select(SettingsRow).where(SettingsRow.id == 1))).scalar_one_or_none()
    if row is None:
        row = SettingsRow(id=1, default_llm_provider="anthropic")
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


def _to_read(row: SettingsRow) -> SettingsRead:
    return SettingsRead(
        default_llm_provider=row.default_llm_provider,
        has_anthropic_api_key=bool(row.anthropic_api_key_enc),
        local_llm_url=row.local_llm_url,
        has_local_llm_api_key=bool(row.local_llm_api_key_enc),
        model_overrides=row.model_overrides or {},
        has_google_oauth_tokens=bool(row.google_oauth_tokens_enc),
        has_smtp_config=bool(row.smtp_config_enc),
        recruiter_name=row.recruiter_name,
        recruiter_email=row.recruiter_email,
        monthly_llm_spend_cap_usd=row.monthly_llm_spend_cap_usd,
    )


@router.get("", response_model=SettingsRead)
async def get_settings(session: AsyncSession = Depends(get_session)) -> SettingsRead:
    row = await _load_or_create(session)
    return _to_read(row)


@router.put("", response_model=SettingsRead)
async def update_settings(
    payload: SettingsUpdate,
    session: AsyncSession = Depends(get_session),
) -> SettingsRead:
    row = await _load_or_create(session)
    cipher = _cipher()
    if payload.default_llm_provider is not None:
        row.default_llm_provider = payload.default_llm_provider
    if payload.anthropic_api_key is not None:
        row.anthropic_api_key_enc = cipher.encrypt(payload.anthropic_api_key)
    if payload.local_llm_url is not None:
        row.local_llm_url = payload.local_llm_url
    if payload.local_llm_api_key is not None:
        row.local_llm_api_key_enc = cipher.encrypt(payload.local_llm_api_key)
    if payload.model_overrides is not None:
        row.model_overrides = payload.model_overrides
    if payload.smtp_config is not None:
        row.smtp_config_enc = cipher.encrypt(json.dumps(payload.smtp_config.model_dump()))
    if payload.recruiter_name is not None:
        row.recruiter_name = payload.recruiter_name
    if payload.recruiter_email is not None:
        row.recruiter_email = payload.recruiter_email
    if payload.monthly_llm_spend_cap_usd is not None:
        row.monthly_llm_spend_cap_usd = payload.monthly_llm_spend_cap_usd
    await session.commit()
    await session.refresh(row)
    return _to_read(row)


def get_smtp_config(row: SettingsRow) -> SmtpConfigInput | None:
    """Decrypt and parse the SMTP config blob from the Settings row."""
    if not row.smtp_config_enc:
        return None
    raw = _cipher().decrypt(row.smtp_config_enc)
    return SmtpConfigInput(**json.loads(raw))
