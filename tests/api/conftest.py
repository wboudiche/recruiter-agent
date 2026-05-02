from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from recruiter.api.candidates import get_engine_dep
from recruiter.api.deps import get_session
from recruiter.config import get_config
from recruiter.main import app
from recruiter.models import Base


@pytest.fixture
async def api_client_unauth(pg_dsn: str) -> AsyncIterator[AsyncClient]:
    """Unauthenticated client. Most tests should NOT use this — use
    api_client (which logs a dev-bypass user in) instead. Reserved for
    auth tests that exercise the unauthenticated path."""
    engine = create_async_engine(pg_dsn)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session() -> AsyncIterator:
        async with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_engine_dep] = lambda: engine
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.fixture
async def api_client(pg_dsn: str, monkeypatch) -> AsyncIterator[AsyncClient]:
    """Authenticated client. Activates the dev-bypass synthetic user so
    every `Depends(require_user)`-gated route succeeds without a real
    OIDC flow. Use api_client_unauth for tests that need the 401 path."""
    monkeypatch.setenv("RECRUITER_DEV_AUTH_BYPASS", "test-user@acme.com")
    monkeypatch.setenv("RECRUITER_OIDC_ISSUER", "")  # safe-by-construction trigger
    get_config.cache_clear()

    engine = create_async_engine(pg_dsn)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session() -> AsyncIterator:
        async with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_engine_dep] = lambda: engine
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
        get_config.cache_clear()
