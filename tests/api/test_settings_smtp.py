import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_put_smtp_config_marks_has_smtp_true(api_client: AsyncClient) -> None:
    resp = await api_client.put(
        "/api/settings",
        json={
            "smtp_config": {
                "host": "smtp.example.com",
                "port": 587,
                "user": "me@example.com",
                "password": "secret",
                "from_email": "me@example.com",
            }
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_smtp_config"] is True
    assert "secret" not in resp.text


@pytest.mark.asyncio
async def test_smtp_password_does_not_leak_in_get(api_client: AsyncClient) -> None:
    await api_client.put(
        "/api/settings",
        json={
            "smtp_config": {
                "host": "smtp.example.com",
                "port": 587,
                "user": "me@example.com",
                "password": "secret",
                "from_email": "me@example.com",
            }
        },
    )
    resp = await api_client.get("/api/settings")
    assert resp.status_code == 200
    assert "secret" not in resp.text
