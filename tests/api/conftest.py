from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from recruiter.api.candidates import get_engine_dep
from recruiter.api.deps import get_session
from recruiter.auth.passwords import hash_password
from recruiter.config import get_config
from recruiter.main import app
from recruiter.models import (
    Application,
    Base,
    Candidate,
    InterviewAssignment,
    InterviewKitRow,
    Job,
    Role,
    Stage,
    User,
)


@pytest.fixture
async def api_client_unauth(pg_dsn: str, monkeypatch) -> AsyncIterator[AsyncClient]:
    """Unauthenticated client. Most tests should NOT use this — use
    api_client (which logs a dev-bypass user in) instead. Reserved for
    auth tests that exercise the unauthenticated path.

    Clears both `RECRUITER_DEV_AUTH_BYPASS` and `RECRUITER_OIDC_ISSUER` so
    that a developer's local `.env` doesn't silently activate dev bypass
    inside tests that explicitly need the 401 path.
    """
    monkeypatch.setenv("RECRUITER_DEV_AUTH_BYPASS", "")
    monkeypatch.setenv("RECRUITER_OIDC_ISSUER", "")
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


@pytest.fixture
def create_scored_app(api_client: AsyncClient):
    """Create a candidate + SCORED application directly via the engine.

    Shared fixture-helper: several API test modules need a bare SCORED
    application to exercise endpoints that only make sense once scoring
    has happened. Returns an async factory so each test can create as many
    as it needs.
    """

    async def _make() -> int:
        job = await api_client.post("/api/jobs", json={
            "title": "Backend", "description": "x", "criteria": []
        })
        job_id = job.json()["id"]
        engine = app.dependency_overrides[get_engine_dep]()
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
        async with SessionLocal() as session:
            c = Candidate(source_type="paste", full_name="Marie", email="m@example.com")
            session.add(c)
            await session.flush()
            a = Application(job_id=job_id, candidate_id=c.id, stage=Stage.SCORED, score=80)
            session.add(a)
            await session.commit()
            return a.id

    return _make


TRACKS_PW = "pw-12345678"


@pytest.fixture
def seed_tracks():
    """Factory for a SCHEDULED application whose live round has two tracks,
    `tech` (question q1) and `rh` (question r1), created in that order.

    `panel` maps a track to its interviewers' emails (VIEWER users with
    password TRACKS_PW, created here); `submitted` lists the emails whose
    sheet is already submitted. Returns (application id, {email: user id}).
    Use with api_client or api_client_unauth: it writes through the engine
    that fixture installed.
    """

    async def _make(
        *, panel: dict[str, list[str]] | None = None, submitted: tuple[str, ...] = (),
    ) -> tuple[int, dict[str, int]]:
        if panel is None:
            panel = {"tech": ["tech@acme.com"], "rh": ["rh@acme.com"]}
        engine = app.dependency_overrides[get_engine_dep]()
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
        async with SessionLocal() as session:
            job = Job(title="Backend", description="x", criteria=[])
            session.add(job)
            await session.flush()
            cand = Candidate(source_type="paste", full_name="Marie", email="m@example.com")
            session.add(cand)
            await session.flush()
            app_row = Application(
                job_id=job.id, candidate_id=cand.id, stage=Stage.SCHEDULED, score=80,
            )
            session.add(app_row)
            await session.flush()
            for track, qid in (("tech", "q1"), ("rh", "r1")):
                session.add(InterviewKitRow(
                    application_id=app_row.id, round=1, track=track, status="ready",
                    questions=[{"id": qid, "text": f"{track} question", "source": "baseline"}],
                ))
                await session.flush()  # ids in creation order
            users: dict[str, int] = {}
            for track, emails in panel.items():
                for email in emails:
                    user = User(email=email, role=Role.VIEWER, is_active=True,
                                password_hash=hash_password(TRACKS_PW))
                    session.add(user)
                    await session.flush()
                    users[email] = user.id
                    session.add(InterviewAssignment(
                        application_id=app_row.id, user_id=user.id, round=1, track=track,
                        submitted_at=datetime.now(UTC) if email in submitted else None,
                    ))
            await session.commit()
            return app_row.id, users

    return _make


@pytest.fixture
def login_as():
    """Log a client in as one of `seed_tracks`' interviewers (password
    TRACKS_PW). Tests that log in several times should also reset the login
    rate limiter, as test_interview_freeze_api.py does."""

    async def _login(client: AsyncClient, email: str) -> None:
        await client.post("/api/auth/logout")
        r = await client.post(
            "/api/auth/login/password", json={"email": email, "password": TRACKS_PW},
        )
        assert r.status_code == 204, r.text

    return _login
