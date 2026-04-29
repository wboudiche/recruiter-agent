import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_application_returns_404_when_missing(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/applications/9999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_applications_for_job(api_client: AsyncClient) -> None:
    job_id = (await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})).json()["id"]

    listing = await api_client.get(f"/api/jobs/{job_id}/applications")
    assert listing.status_code == 200
    assert listing.json() == []
