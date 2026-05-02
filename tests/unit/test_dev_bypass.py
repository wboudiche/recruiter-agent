import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.auth.dev_bypass import maybe_resolve
from recruiter.config import get_config


@pytest.fixture(autouse=True)
def _reset_config_cache():
    get_config.cache_clear()
    yield
    get_config.cache_clear()


@pytest.mark.asyncio
async def test_returns_none_when_no_bypass_set(
    db_session_with_schema: AsyncSession, monkeypatch,
) -> None:
    monkeypatch.setenv("RECRUITER_DEV_AUTH_BYPASS", "")
    monkeypatch.setenv("RECRUITER_OIDC_ISSUER", "")
    get_config.cache_clear()
    assert await maybe_resolve(db_session_with_schema) is None


@pytest.mark.asyncio
async def test_returns_none_when_oidc_is_configured(
    db_session_with_schema: AsyncSession, monkeypatch,
) -> None:
    """Safety: bypass MUST NOT activate if a real IdP is configured."""
    monkeypatch.setenv("RECRUITER_DEV_AUTH_BYPASS", "alice@acme.com")
    monkeypatch.setenv("RECRUITER_OIDC_ISSUER", "https://accounts.google.com")
    get_config.cache_clear()
    assert await maybe_resolve(db_session_with_schema) is None


@pytest.mark.asyncio
async def test_creates_user_on_first_call(
    db_session_with_schema: AsyncSession, monkeypatch,
) -> None:
    monkeypatch.setenv("RECRUITER_DEV_AUTH_BYPASS", "alice@acme.com")
    monkeypatch.setenv("RECRUITER_OIDC_ISSUER", "")
    get_config.cache_clear()
    user = await maybe_resolve(db_session_with_schema)
    assert user is not None
    assert user.email == "alice@acme.com"


@pytest.mark.asyncio
async def test_returns_existing_user_on_subsequent_calls(
    db_session_with_schema: AsyncSession, monkeypatch,
) -> None:
    monkeypatch.setenv("RECRUITER_DEV_AUTH_BYPASS", "alice@acme.com")
    monkeypatch.setenv("RECRUITER_OIDC_ISSUER", "")
    get_config.cache_clear()
    u1 = await maybe_resolve(db_session_with_schema)
    u2 = await maybe_resolve(db_session_with_schema)
    assert u1.id == u2.id  # same row
