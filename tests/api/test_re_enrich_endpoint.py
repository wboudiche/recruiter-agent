import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from recruiter.api.candidates import get_engine_dep, get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.models import Application, Candidate, Stage


async def _seed_application(
    api_client: AsyncClient, *, enrichment: dict | None = None, stage: Stage = Stage.SCORED
) -> tuple[int, int]:
    """Create a job + candidate + application directly via the engine.

    Returns (job_id, application_id). Mirrors the helper used in
    tests/api/test_chat_search_tool.py."""
    job = await api_client.post(
        "/api/jobs", json={"title": "Backend", "description": "x", "criteria": []}
    )
    job_id = job.json()["id"]
    engine = app.dependency_overrides[get_engine_dep]()
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        candidate = Candidate(
            source_type="paste",
            full_name="Marie",
            email="m@example.com",
            raw_extracted={"text": "resume body"},
        )
        session.add(candidate)
        await session.flush()
        app_row = Application(
            job_id=job_id,
            candidate_id=candidate.id,
            stage=stage,
            score=80,
            enrichment=enrichment,
        )
        session.add(app_row)
        await session.commit()
        return job_id, app_row.id


@pytest.mark.asyncio
async def test_re_enrich_clears_bundle_and_returns_202(api_client: AsyncClient) -> None:
    # FastAPI resolves get_llm before the handler runs; provide a fake so
    # the request gets to the handler. The orchestrator runs as a background
    # task and is fire-and-forget for our assertions on stage/enrichment.
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()
    try:
        _, app_id = await _seed_application(
            api_client, enrichment={"results": [{"x": 1}]}
        )
        r = await api_client.post(f"/api/applications/{app_id}/re-enrich")
        assert r.status_code == 202, r.text

        # The route handler clears the bundle and flips stage to
        # ENRICHING synchronously, then schedules the orchestrator's
        # re-enrich entry point as a background task. With the new
        # fast path (no re-extract / re-score), that task can finish
        # before this assertion reads the row — so we accept either
        # the intermediate ENRICHING state OR the post-completion
        # SCORED state. Both are correct outcomes from the user's
        # perspective.
        engine = app.dependency_overrides[get_engine_dep]()
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
        async with SessionLocal() as session:
            row = await session.get(Application, app_id)
            assert row is not None
            assert row.stage.value in {"enriching", "scored"}, row.stage.value
            # The seeded bundle ({"results": [...]}) is gone. After the
            # background task, the bundle may be either None or the new
            # fresh enrichment payload — both mean "the stale bundle
            # was cleared".
            if row.enrichment is not None:
                assert row.enrichment.get("results") != [{"x": 1}]
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_re_enrich_404_for_unknown_app(api_client: AsyncClient) -> None:
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()
    try:
        r = await api_client.post("/api/applications/9999/re-enrich")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_settings_round_trip_for_enrichment_fields(api_client: AsyncClient) -> None:
    payload = {
        "enrichment_enabled": True,
        "enrichment_twitter_api_key": "twk",
        "enrichment_sources": {"twitter": False, "youtube": True},
    }
    r = await api_client.put("/api/settings", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enrichment_enabled"] is True
    assert body["has_enrichment_twitter_api_key"] is True
    assert body["enrichment_sources"]["twitter"] is False
    # Round-trip via GET.
    r = await api_client.get("/api/settings")
    body = r.json()
    assert body["enrichment_enabled"] is True
    assert body["has_enrichment_twitter_api_key"] is True
    assert body["enrichment_sources"] == {"twitter": False, "youtube": True}


@pytest.mark.asyncio
async def test_application_read_includes_enrichment(api_client: AsyncClient) -> None:
    bundle = {
        "results": [],
        "errors": [],
        "discovery_consent": False,
        "fetched_at": "2026-05-10T00:00:00Z",
        "expires_at": "2026-06-09T00:00:00Z",
    }
    _, app_id = await _seed_application(api_client, enrichment=bundle)
    r = await api_client.get(f"/api/applications/{app_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "enrichment" in body
    assert body["enrichment"]["results"] == []
    assert body["enrichment"]["fetched_at"] == "2026-05-10T00:00:00Z"
