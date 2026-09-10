import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

from recruiter.api.candidates import get_engine_dep, get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.models import Application, Stage
from recruiter.schemas.interview import GeneratedQuestion, GeneratedQuestions


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


def _fake_llm_with_one_question() -> FakeLLMClient:
    return FakeLLMClient(
        structured_responses=[GeneratedQuestions(questions=[
            GeneratedQuestion(text="Tell me about a production incident.",
                               criterion="reliability"),
        ])],
    )


@pytest.mark.asyncio
async def test_moving_to_scheduled_starts_a_kit(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """A real, LLM-backed generation: proves the background task actually
    ran and produced probe questions, not just that some kit object exists."""
    app.dependency_overrides[get_llm] = _fake_llm_with_one_question
    try:
        app_id = await create_scored_app()
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
        await _move_to_invited(api_client, app_id)

        resp = await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})
        assert resp.status_code == 200

        kit = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()["kit"]
        assert kit is not None
        # The in-process ASGI transport runs BackgroundTasks to completion
        # before the response is handed back (see the docstring on
        # test_generate_returns_202_and_kit_is_no_longer_null in
        # test_interview_api.py), so generation has already finished by
        # the time this GET runs.
        assert kit["status"] == "ready"
        assert any(q["source"] == "probe" for q in kit["questions"])
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_a_failing_generation_still_leaves_the_candidate_scheduled(
    api_client: AsyncClient, create_scored_app, monkeypatch,
) -> None:
    """The whole background-task design exists for this. An LLM outage must
    never strand a candidate between stages — and the failure must actually
    be caught by run_generate_kit (kit ends up "error"), not merely never
    triggered (which would make the stage assertion below vacuous)."""
    from recruiter.api import interview

    async def boom(**kwargs):
        raise RuntimeError("model unavailable")

    # get_llm must resolve to a real client so patch_application takes the
    # enqueue branch (llm is not None) rather than the "no LLM configured"
    # branch — otherwise run_generate_kit, and therefore `boom`, never runs.
    app.dependency_overrides[get_llm] = _fake_llm_with_one_question
    monkeypatch.setattr(interview, "generate_probes", boom)
    try:
        app_id = await create_scored_app()
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
        await _move_to_invited(api_client, app_id)

        resp = await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})
        assert resp.status_code == 200

        app_read = (await api_client.get(f"/api/applications/{app_id}")).json()
        assert app_read["stage"] == "scheduled", "a failed kit must not affect the stage"

        kit = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()["kit"]
        assert kit["status"] == "error", (
            "must show the generation was actually attempted and caught, "
            "not merely never triggered"
        )
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_re_entering_scheduled_preserves_answered_questions(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """A candidate rejected after an interview, then reconsidered and
    rescheduled, must not lose recorded answers/ratings from the first
    round. Exercises the real business path back to SCHEDULED: interviewed
    -> rejected -> scored -> validated -> (direct DB) invited -> scheduled."""
    app_id = await create_scored_app()
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
    await _move_to_invited(api_client, app_id)
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})

    # Record an answered, rated question on the kit created by the first
    # SCHEDULED transition above.
    answered = {"id": "q1", "text": "Tell me about a production incident.",
                "source": "probe", "answer": "Handled a prod outage calmly.",
                "rating": "strong"}
    patch_resp = await api_client.patch(
        f"/api/applications/{app_id}/interview-kit", json={"questions": [answered]},
    )
    assert patch_resp.status_code == 200

    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "interviewed"})
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "rejected"})
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scored"})
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
    await _move_to_invited(api_client, app_id)

    resp = await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})
    assert resp.status_code == 200

    kit = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()["kit"]
    questions = kit["questions"]
    assert len(questions) == 1
    assert questions[0]["answer"] == "Handled a prod outage calmly."
    assert questions[0]["rating"] == "strong"
