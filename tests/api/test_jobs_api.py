import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_and_list_jobs(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/jobs",
        json={"title": "Backend", "description": "Rust APIs", "criteria": []},
    )
    assert resp.status_code == 201, resp.text
    job = resp.json()
    assert job["title"] == "Backend"
    assert job["status"] == "open"

    listing = await api_client.get("/api/jobs")
    assert listing.status_code == 200
    assert len(listing.json()) == 1


@pytest.mark.asyncio
async def test_get_job_returns_404_when_missing(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/jobs/9999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_job(api_client: AsyncClient) -> None:
    created = (await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})).json()
    resp = await api_client.patch(f"/api/jobs/{created['id']}", json={"title": "T2"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "T2"
