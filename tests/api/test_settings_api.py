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
