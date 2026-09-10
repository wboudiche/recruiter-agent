import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_put_and_read_back_the_baseline(api_client: AsyncClient) -> None:
    job = (await api_client.post("/api/jobs", json={
        "title": "SRE", "description": "d", "criteria": [],
    })).json()
    body = {"questions": [{"id": "b1", "text": "Why this role?"}]}

    resp = await api_client.put(f"/api/jobs/{job['id']}/interview-baseline", json=body)
    assert resp.status_code == 200

    read = (await api_client.get(f"/api/jobs/{job['id']}")).json()
    assert read["interview_baseline"][0]["text"] == "Why this role?"


@pytest.mark.asyncio
async def test_baseline_rejects_duplicate_ids(api_client: AsyncClient) -> None:
    job = (await api_client.post("/api/jobs", json={
        "title": "SRE", "description": "d", "criteria": [],
    })).json()
    body = {"questions": [{"id": "b1", "text": "One"}, {"id": "b1", "text": "Two"}]}
    resp = await api_client.put(f"/api/jobs/{job['id']}/interview-baseline", json=body)
    assert resp.status_code == 422
