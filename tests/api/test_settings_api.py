import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_settings_default_when_unset(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["default_llm_provider"] == "anthropic"
    assert body["has_anthropic_api_key"] is False


@pytest.mark.asyncio
async def test_update_settings_encrypts_secret(api_client: AsyncClient) -> None:
    resp = await api_client.put(
        "/api/settings",
        json={"anthropic_api_key": "sk-ant-test", "recruiter_email": "me@example.com"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_anthropic_api_key"] is True
    assert "sk-ant-test" not in resp.text  # secret is not echoed
    assert body["recruiter_email"] == "me@example.com"


@pytest.mark.asyncio
async def test_update_settings_encrypts_local_llm_api_key(api_client: AsyncClient) -> None:
    initial = await api_client.get("/api/settings")
    assert initial.json()["has_local_llm_api_key"] is False

    resp = await api_client.put(
        "/api/settings",
        json={"local_llm_api_key": "sk-linagora-secret"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_local_llm_api_key"] is True
    assert "sk-linagora-secret" not in resp.text  # secret is not echoed


@pytest.mark.asyncio
async def test_put_settings_persists_search_provider_and_keys(
    api_client: AsyncClient,
) -> None:
    r = await api_client.put("/api/settings", json={
        "search_provider": "google_cse",
        "search_api_key": "google-api-key",
        "search_engine_id": "abcd1234:efgh5678",
        "github_token": "ghp_xxx",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["search_provider"] == "google_cse"
    assert body["search_engine_id"] == "abcd1234:efgh5678"
    assert body["has_search_api_key"] is True
    assert body["has_github_token"] is True
    # Round-trip: GET reflects what we set.
    r = await api_client.get("/api/settings")
    body = r.json()
    assert body["search_provider"] == "google_cse"
    assert body["has_search_api_key"] is True


@pytest.mark.asyncio
async def test_get_settings_defaults_search_unset(api_client: AsyncClient) -> None:
    r = await api_client.get("/api/settings")
    body = r.json()
    assert body["search_provider"] is None
    assert body["search_engine_id"] is None
    assert body["has_search_api_key"] is False
    assert body["has_github_token"] is False


# --- revoking stored credentials -----------------------------------------
# Until these, a stored secret could only ever be overwritten, never removed:
# the UI omits blank fields and the API only ever wrote a value. A key you
# decided to stop trusting was stuck in the database.

SECRET_FIELDS = [
    ("anthropic_api_key", "has_anthropic_api_key"),
    ("local_llm_api_key", "has_local_llm_api_key"),
    ("search_api_key", "has_search_api_key"),
    ("github_token", "has_github_token"),
    ("apify_api_key", "has_apify_api_key"),
    ("enrichment_twitter_api_key", "has_enrichment_twitter_api_key"),
    ("enrichment_youtube_api_key", "has_enrichment_youtube_api_key"),
    ("enrichment_stackexchange_key", "has_enrichment_stackexchange_key"),
]


@pytest.mark.parametrize("field,has_flag", SECRET_FIELDS)
@pytest.mark.asyncio
async def test_empty_string_revokes_stored_secret(
    api_client: AsyncClient, field: str, has_flag: str,
) -> None:
    stored = await api_client.put("/api/settings", json={field: "some-secret-value"})
    assert stored.status_code == 200
    assert stored.json()[has_flag] is True

    revoked = await api_client.put("/api/settings", json={field: ""})
    assert revoked.status_code == 200
    assert revoked.json()[has_flag] is False, f"{field} was not revoked"

    # and it stays gone across a fresh read
    assert (await api_client.get("/api/settings")).json()[has_flag] is False


@pytest.mark.parametrize("field,has_flag", SECRET_FIELDS)
@pytest.mark.asyncio
async def test_omitting_a_secret_leaves_it_untouched(
    api_client: AsyncClient, field: str, has_flag: str,
) -> None:
    """The counterpart guard: saving unrelated settings must not wipe keys."""
    await api_client.put("/api/settings", json={field: "some-secret-value"})

    resp = await api_client.put("/api/settings", json={"recruiter_name": "Walid"})
    assert resp.status_code == 200
    assert resp.json()[has_flag] is True, f"{field} was clobbered by an unrelated save"


@pytest.mark.asyncio
async def test_padded_secret_is_stored_stripped(api_client: AsyncClient) -> None:
    """A token pasted from a terminal carries a trailing newline. Stored raw it
    goes out as `Authorization: Bearer ghp_x\n` and the provider answers 401 —
    while the UI insists a key is set."""
    resp = await api_client.put("/api/settings", json={"github_token": "  ghp_padded\n"})
    assert resp.status_code == 200
    assert resp.json()["has_github_token"] is True

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from recruiter.api.candidates import get_engine_dep
    from recruiter.api.settings import _cipher
    from recruiter.main import app
    from recruiter.models import SettingsRow

    engine = app.dependency_overrides[get_engine_dep]()
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        row = (await session.execute(select(SettingsRow).where(SettingsRow.id == 1))).scalar_one()
        assert _cipher().decrypt(row.github_token_enc) == "ghp_padded"


@pytest.mark.asyncio
async def test_whitespace_only_secret_revokes_rather_than_storing_blanks(
    api_client: AsyncClient,
) -> None:
    """Whitespace is not a credential. Stored as one it produces the same 401
    the empty-string revoke exists to avoid."""
    await api_client.put("/api/settings", json={"github_token": "ghp_real"})
    resp = await api_client.put("/api/settings", json={"github_token": "   "})
    assert resp.status_code == 200
    assert resp.json()["has_github_token"] is False
