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
