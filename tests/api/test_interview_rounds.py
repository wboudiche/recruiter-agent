"""Reopening an interviewed application for another round.

Before rounds existed, `scheduled` was reachable only from `invited`, so
a second interview meant driving the candidate through REJECTED and
re-sending an invitation. See the migration for the full story.
"""
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from recruiter.api.candidates import get_engine_dep, get_llm
from recruiter.main import app
from recruiter.models import Application, InterviewAssignment, Role, Stage, User
from recruiter.models.interview_kit_row import InterviewKitRow
from recruiter.llm.client import FakeLLMClient
from recruiter.schemas.interview import GeneratedQuestion, GeneratedQuestions


def _fake_llm() -> FakeLLMClient:
    return FakeLLMClient(structured_responses=[GeneratedQuestions(questions=[
        GeneratedQuestion(text="Describe a production incident.", criterion="reliability"),
    ])])


async def _sessionmaker():
    return async_sessionmaker(
        app.dependency_overrides[get_engine_dep](), expire_on_commit=False,
    )


async def _interviewed_with_panel(api_client: AsyncClient, app_id: int) -> list[int]:
    """Drive an application to INTERVIEWED with a two-person panel, both
    submitted. Returns their user ids."""
    SessionLocal = await _sessionmaker()
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
    async with SessionLocal() as session:
        await session.execute(
            update(Application).where(Application.id == app_id).values(stage=Stage.INVITED)
        )
        await session.commit()
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})

    async with SessionLocal() as session:
        ids = []
        for email in ("ana@acme.com", "ben@acme.com"):
            u = User(email=email, role=Role.VIEWER, is_active=True)
            session.add(u)
            await session.flush()
            ids.append(u.id)
        await session.commit()
    await api_client.put(f"/api/applications/{app_id}/interviewers", json={"user_ids": ids})

    async with SessionLocal() as session:
        rows = (await session.execute(
            select(InterviewAssignment).where(InterviewAssignment.application_id == app_id)
        )).scalars().all()
        for r in rows:
            r.submitted_at = datetime.now(UTC)
            r.sheet = {"answers": {"q-1": {"answer": "said a thing", "rating": "strong"}},
                       "verdict": {"decision": "unsure", "note": None}}
        await session.commit()
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "interviewed"})
    return ids


@pytest.mark.asyncio
async def test_reopening_bumps_the_round_and_carries_the_panel_forward(
    api_client: AsyncClient, create_scored_app,
) -> None:
    app.dependency_overrides[get_llm] = _fake_llm
    try:
        app_id = await create_scored_app()
        ids = await _interviewed_with_panel(api_client, app_id)

        resp = await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})
        assert resp.status_code == 200, resp.text

        SessionLocal = await _sessionmaker()
        async with SessionLocal() as session:
            row = await session.get(Application, app_id)
            rows = (await session.execute(
                select(InterviewAssignment).where(InterviewAssignment.application_id == app_id)
            )).scalars().all()

        assert row.interview_round == 2
        assert row.stage == Stage.SCHEDULED
        # Round 1 is untouched history.
        r1 = [r for r in rows if r.round == 1]
        assert len(r1) == 2 and all(r.submitted_at is not None for r in r1)
        assert all(r.sheet["answers"] for r in r1), "round 1 feedback was wiped"
        # Round 2 is the same people, with fresh sheets to fill in.
        r2 = [r for r in rows if r.round == 2]
        assert {r.user_id for r in r2} == set(ids)
        assert all(r.submitted_at is None for r in r2)
        assert all(not r.sheet.get("answers") for r in r2), "round 2 inherited round 1's answers"
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_reopening_does_not_close_the_round_immediately(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """Round 1's rows stay submitted forever. If completion were evaluated
    across every round the candidate would snap straight back to
    INTERVIEWED the moment they were reopened."""
    app.dependency_overrides[get_llm] = _fake_llm
    try:
        app_id = await create_scored_app()
        await _interviewed_with_panel(api_client, app_id)

        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})

        body = (await api_client.get(f"/api/applications/{app_id}")).json()
        assert body["stage"] == "scheduled"
        assert body["interviewed_at"] is None, "a reopened round kept its closing timestamp"
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_reopening_keeps_the_shared_questions(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """The kit is one shared blob and round 1's answers are keyed to its
    question ids, so reopening must not regenerate them away."""
    app.dependency_overrides[get_llm] = _fake_llm
    try:
        app_id = await create_scored_app()
        await _interviewed_with_panel(api_client, app_id)
        before = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()
        before_ids = [q["id"] for q in before["kit"]["questions"]]

        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})

        after = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()
        assert [q["id"] for q in after["kit"]["questions"]] == before_ids
        assert after["kit"]["closed_at"] is None, "the reopened kit is still marked closed"
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_questions_stay_frozen_into_the_next_round(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """Round 1's submitted answers are keyed to the shared question ids, so
    the freeze has to outlive the round that caused it. Removing a question
    in round 2 is still refused."""
    app.dependency_overrides[get_llm] = _fake_llm
    try:
        app_id = await create_scored_app()
        await _interviewed_with_panel(api_client, app_id)
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})

        kit = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()["kit"]
        assert len(kit["questions"]) >= 1
        # Drop one question: legal while nothing is submitted, refused after.
        resp = await api_client.patch(
            f"/api/applications/{app_id}/interview-kit",
            json={"questions": kit["questions"][1:]},
        )

        assert resp.status_code == 409, resp.text
        assert "frozen" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_llm, None)


async def _kit_rows(app_id: int) -> list[InterviewKitRow]:
    SessionLocal = await _sessionmaker()
    async with SessionLocal() as session:
        return list((await session.execute(
            select(InterviewKitRow)
            .where(InterviewKitRow.application_id == app_id)
            .order_by(InterviewKitRow.round)
        )).scalars().all())


@pytest.mark.asyncio
async def test_entering_scheduled_creates_a_kit_row(
    api_client: AsyncClient, create_scored_app,
) -> None:
    app.dependency_overrides[get_llm] = _fake_llm
    try:
        app_id = await create_scored_app()
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
        SessionLocal = await _sessionmaker()
        async with SessionLocal() as session:
            await session.execute(
                update(Application).where(Application.id == app_id).values(stage=Stage.INVITED))
            await session.commit()

        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})

        rows = await _kit_rows(app_id)
        assert [(r.round, r.track) for r in rows] == [(1, "default")]
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_reopening_creates_the_next_rounds_kit_rather_than_mutating_the_first(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """Round one's row must survive untouched — its closed_at is the record
    that the round happened, and its questions anchor round one's answers."""
    app.dependency_overrides[get_llm] = _fake_llm
    try:
        app_id = await create_scored_app()
        await _interviewed_with_panel(api_client, app_id)
        before = await _kit_rows(app_id)
        assert len(before) == 1 and before[0].closed_at is not None
        first_questions = list(before[0].questions)

        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})

        rows = await _kit_rows(app_id)
        assert [r.round for r in rows] == [1, 2]
        assert rows[0].closed_at is not None, "round one was reopened instead of round two"
        assert rows[1].closed_at is None
        assert [q["id"] for q in rows[1].questions] == [q["id"] for q in first_questions]
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_generate_creates_a_kit_when_the_application_has_none(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """The "Generate interview kit" button works from a standing start, so
    generate must create the row rather than 404 on a missing one."""
    app_id = await create_scored_app()
    llm = _fake_llm()
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        resp = await api_client.post(f"/api/applications/{app_id}/interview-kit/generate")
        assert resp.status_code == 202, resp.text
    finally:
        app.dependency_overrides.pop(get_llm, None)

    rows = await _kit_rows(app_id)
    assert [(r.round, r.track) for r in rows] == [(1, "default")]
    assert rows[0].questions, "generation produced no questions"
