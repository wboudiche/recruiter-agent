import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_preflight_allows_dev_origin(api_client: AsyncClient) -> None:
    resp = await api_client.options(
        "/api/jobs",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resp.status_code in (200, 204)
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"
