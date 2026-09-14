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
    -> rejected -> scored -> validated -> (direct DB) invited -> scheduled.

    get_llm is overridden with a fake, exactly like the two tests above, so
    the second SCHEDULED transition actually runs run_generate_kit ->
    merge_regenerated instead of taking the no-LLM error branch. Without
    the override this test would pass even if merge_regenerated were
    deleted — see test_interview_kit_merge_actually_runs below, which
    checks that directly.

    Answer/rating are written directly to the stored kit rather than via
    PATCH .../interview-kit: those fields are legacy (per-interviewer
    feedback now lives on sheets — see recruiter.schemas.interview) and
    the endpoint never takes them from the client, so this mimics a kit
    recorded before that change."""
    app.dependency_overrides[get_llm] = _fake_llm_with_one_question
    try:
        app_id = await create_scored_app()
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
        await _move_to_invited(api_client, app_id)
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})

        # Mark the probe question generated by the first SCHEDULED transition
        # above as answered and rated, directly in storage. A raw UPDATE,
        # not an ORM attribute mutation: assigning a JSON column back to
        # itself in place leaves it byte-for-byte identical to the value
        # SQLAlchemy already has loaded, so it is never flagged dirty and
        # the write silently would not persist.
        engine = app.dependency_overrides[get_engine_dep]()
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
        async with SessionLocal() as session:
            row = await session.get(Application, app_id)
            kit = row.interview_kit
            answered_id = kit["questions"][0]["id"]
            new_kit = {
                **kit,
                "questions": [
                    {**kit["questions"][0], "answer": "Handled a prod outage calmly.",
                     "rating": "strong"},
                    *kit["questions"][1:],
                ],
            }
            await session.execute(
                update(Application).where(Application.id == app_id).values(interview_kit=new_kit)
            )
            await session.commit()

        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "interviewed"})
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "rejected"})
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scored"})
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
        await _move_to_invited(api_client, app_id)

        resp = await api_client.patch(
            f"/api/applications/{app_id}", json={"stage": "scheduled"},
        )
        assert resp.status_code == 200

        kit = (await api_client.get(
            f"/api/applications/{app_id}/interview-kit",
        )).json()["kit"]
        questions = kit["questions"]
        # The real regeneration path both keeps the answered question
        # verbatim AND appends a freshly generated probe alongside it —
        # merge_regenerated always regenerates probes, on top of whatever
        # was already answered.
        assert len(questions) == 2
        answered_q = next(q for q in questions if q["id"] == answered_id)
        assert answered_q["answer"] == "Handled a prod outage calmly."
        assert answered_q["rating"] == "strong"
    finally:
        app.dependency_overrides.pop(get_llm, None)
