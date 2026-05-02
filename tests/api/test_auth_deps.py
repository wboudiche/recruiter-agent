import pytest
from fastapi import FastAPI, Depends
from httpx import ASGITransport, AsyncClient

from recruiter.api.deps import require_user
from recruiter.api.origin_check import OriginCheckMiddleware
from recruiter.config import get_config


@pytest.fixture(autouse=True)
def _reset_config():
    get_config.cache_clear()
    yield
    get_config.cache_clear()


@pytest.mark.asyncio
async def test_require_user_returns_401_without_cookie(api_client: AsyncClient) -> None:
    r = await api_client.get("/api/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_origin_middleware_blocks_disallowed_origin(monkeypatch) -> None:
    monkeypatch.setenv("RECRUITER_ALLOWED_ORIGINS", "http://localhost:5173")
    get_config.cache_clear()

    test_app = FastAPI()
    test_app.add_middleware(OriginCheckMiddleware)

    @test_app.post("/poke")
    async def poke():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
        bad = await c.post("/poke", headers={"Origin": "http://attacker.example.com"})
        assert bad.status_code == 403
        good = await c.post("/poke", headers={"Origin": "http://localhost:5173"})
        assert good.status_code == 200
        # No Origin header (e.g., curl, server-to-server) → allowed.
        no_origin = await c.post("/poke")
        assert no_origin.status_code == 200


@pytest.mark.asyncio
async def test_origin_middleware_ignores_get(monkeypatch) -> None:
    """Read-only requests don't get the Origin check (they don't mutate)."""
    monkeypatch.setenv("RECRUITER_ALLOWED_ORIGINS", "http://localhost:5173")
    get_config.cache_clear()

    test_app = FastAPI()
    test_app.add_middleware(OriginCheckMiddleware)

    @test_app.get("/peek")
    async def peek():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
        r = await c.get("/peek", headers={"Origin": "http://attacker.example.com"})
        assert r.status_code == 200
