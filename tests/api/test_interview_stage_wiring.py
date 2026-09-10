import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

from recruiter.api.candidates import get_engine_dep
from recruiter.main import app
from recruiter.models import Application, Stage


async def _move_to_invited(api_client: AsyncClient, app_id: int) -> None:
    """`ApplicationUpdate.stage` has no "invited" literal, so a candidate
    cannot be PATCHed through it via the API. Set it directly, mirroring
    the direct-DB helper pattern in tests/api/test_interview_submit.py."""
    engine = app.dependency_overrides[get_engine_dep]()
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        await session.execute(
            update(Application).where(Application.id == app_id).values(stage=Stage.INVITED)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_moving_to_scheduled_starts_a_kit(
    api_client: AsyncClient, create_scored_app,
) -> None:
    app_id = await create_scored_app()
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
    await _move_to_invited(api_client, app_id)

    resp = await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})
    assert resp.status_code == 200

    kit = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()["kit"]
    assert kit is not None
    assert kit["status"] in ("generating", "ready", "error")


@pytest.mark.asyncio
async def test_a_failing_generation_still_leaves_the_candidate_scheduled(
    api_client: AsyncClient, create_scored_app, monkeypatch,
) -> None:
    """The whole background-task design exists for this. An LLM outage must
    never strand a candidate between stages."""
    from recruiter.api import interview

    async def boom(**kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(interview, "generate_probes", boom)

    app_id = await create_scored_app()
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
    await _move_to_invited(api_client, app_id)

    resp = await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})
    assert resp.status_code == 200

    app = (await api_client.get(f"/api/applications/{app_id}")).json()
    assert app["stage"] == "scheduled", "a failed kit must not affect the stage"
