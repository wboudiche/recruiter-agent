"""Tests for the live-wired get_llm dependency that resolves LLM client from settings.

These tests do NOT override get_llm — they exercise the real resolution path that
reads the Settings singleton row.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_llm_returns_503_when_settings_missing(api_client: AsyncClient) -> None:
    """No settings row in DB → 503 when adding a candidate."""
    job_id = (await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})).json()["id"]
    resp = await api_client.post(
        f"/api/jobs/{job_id}/candidates",
        json={"kind": "paste", "content": "Alice"},
    )
    assert resp.status_code == 503
    assert "Settings not configured" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_llm_returns_503_when_anthropic_key_missing(api_client: AsyncClient) -> None:
    """Settings exist but anthropic key is not set → 503."""
    # Create the settings row by GET-ing (auto-creates with default_llm_provider="anthropic")
    await api_client.get("/api/settings")
    job_id = (await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})).json()["id"]
    resp = await api_client.post(
        f"/api/jobs/{job_id}/candidates",
        json={"kind": "paste", "content": "Alice"},
    )
    assert resp.status_code == 503
    assert "Anthropic API key not set" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_llm_resolves_anthropic_when_key_present(api_client: AsyncClient) -> None:
    """Settings has provider=anthropic and key → request succeeds (returns 202).

    This doesn't actually call Anthropic — the BackgroundTask runs after the response
    is sent and would fail with auth errors, but the endpoint itself returns 202.
    """
    await api_client.put("/api/settings", json={"anthropic_api_key": "sk-ant-fake-but-resolves"})
    job_id = (await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})).json()["id"]
    resp = await api_client.post(
        f"/api/jobs/{job_id}/candidates",
        json={"kind": "paste", "content": "Alice"},
    )
    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_get_llm_returns_503_when_local_url_missing(api_client: AsyncClient) -> None:
    """Settings has provider=local but no URL → 503."""
    await api_client.put("/api/settings", json={"default_llm_provider": "local"})
    job_id = (await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})).json()["id"]
    resp = await api_client.post(
        f"/api/jobs/{job_id}/candidates",
        json={"kind": "paste", "content": "Alice"},
    )
    assert resp.status_code == 503
    assert "Local LLM URL not set" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_llm_returns_503_for_unknown_provider(api_client: AsyncClient) -> None:
    """Settings has unknown provider → 503."""
    await api_client.put("/api/settings", json={"default_llm_provider": "made-up"})
    job_id = (await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})).json()["id"]
    resp = await api_client.post(
        f"/api/jobs/{job_id}/candidates",
        json={"kind": "paste", "content": "Alice"},
    )
    assert resp.status_code == 503
    assert "Unknown LLM provider" in resp.json()["detail"]
