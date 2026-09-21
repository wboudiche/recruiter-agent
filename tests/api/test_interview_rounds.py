"""Reopening an interviewed application for another round.

Before rounds existed, `scheduled` was reachable only from `invited`, so
a second interview meant driving the candidate through REJECTED and
re-sending an invitation. See the migration for the full story.
"""
import asyncio
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from recruiter.api.candidates import get_engine_dep, get_llm
from recruiter.api.interview import run_generate_kit
from recruiter.events import EventBus
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
async def test_round_two_questions_are_editable_after_round_one_closed(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """Round 1's submitted answers are keyed to round 1's own kit now, so
    round 1 closing does not freeze round 2's questions. Removing a
    question in round 2 is allowed."""
    app.dependency_overrides[get_llm] = _fake_llm
    try:
        app_id = await create_scored_app()
        await _interviewed_with_panel(api_client, app_id)
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})

        kit = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()["kit"]
        assert len(kit["questions"]) >= 1
        # Drop one question: legal while nothing is submitted, and still
        # legal here because round 2 has nothing submitted of its own.
        resp = await api_client.patch(
            f"/api/applications/{app_id}/interview-kit",
            json={"questions": kit["questions"][1:]},
        )

        assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_a_reopened_round_can_regenerate_its_questions(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """Round one's answers are keyed to round one's kit, so regenerating
    round two cannot orphan them. Before kits were rows the freeze had to
    span every round, which left a reopened round permanently stuck with
    the questions it inherited."""
    app.dependency_overrides[get_llm] = _fake_llm
    try:
        app_id = await create_scored_app()
        await _interviewed_with_panel(api_client, app_id)
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})

        resp = await api_client.post(f"/api/applications/{app_id}/interview-kit/generate")

        assert resp.status_code == 202, resp.text
        kit = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()["kit"]
        assert kit["status"] == "ready"
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


@pytest.mark.asyncio
async def test_round_bump_during_generation_does_not_write_the_old_rounds_row(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """SCHEDULED -> INTERVIEWED -> SCHEDULED is a legal one-click round
    trip. If a recruiter does that while round one's regeneration is still
    waiting on the model, `run_generate_kit` must not write onto round
    one's now-closed row: the freeze guard only inspects the CURRENT
    round's rows, which are empty right after the bump, so it cannot catch
    this on its own — the fix re-resolves the kit row after the lock and
    abandons the write if the round moved."""
    app_id = await create_scored_app()
    engine = app.dependency_overrides[get_engine_dep]()
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    closed_at = datetime.now(UTC).isoformat()
    async with SessionLocal() as session:
        session.add(InterviewKitRow(
            application_id=app_id, round=1, track="default", status="ready",
            questions=[{"id": "q1", "text": "Why?", "source": "probe"}],
            closed_at=closed_at,
        ))
        await session.commit()

    class _BumpsRoundMidCall:
        """Closes and reopens the round from another session while the
        model 'thinks', simulating a recruiter's one-click round trip
        landing in the middle of a model call."""

        async def chat_structured(self, *a: object, **kw: object) -> GeneratedQuestions:
            async with SessionLocal() as other:
                app_row = await other.get(Application, app_id)
                app_row.interview_round = 2
                other.add(InterviewKitRow(
                    application_id=app_id, round=2, track="default",
                    status="ready", questions=[],
                ))
                await other.commit()
            return GeneratedQuestions(questions=[
                GeneratedQuestion(text="A freshly generated probe.", criterion="reliability"),
            ])

    await run_generate_kit(
        application_id=app_id, engine=engine, llm=_BumpsRoundMidCall(), bus=EventBus(),
    )

    async with SessionLocal() as session:
        round_one = (await session.execute(
            select(InterviewKitRow).where(
                InterviewKitRow.application_id == app_id, InterviewKitRow.round == 1,
            )
        )).scalar_one()

    assert round_one.closed_at == closed_at, "generation reopened a closed round"
    assert [q["id"] for q in round_one.questions] == ["q1"], (
        "generation rewrote a historical round's questions"
    )


@pytest.mark.asyncio
async def test_a_question_answered_in_round_one_can_be_reworded_in_round_two(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """The reword guard on PATCH /interview-kit (interview.py's "cannot
    reword a question that has been answered in a submitted sheet") must
    be scoped to the CURRENT round, like the freeze check right next to
    it. Unscoped, a question answered in round one's SUBMITTED sheet stays
    locked in round two forever — even though round two copies its
    question ids onto its OWN row, so editing round two can never orphan
    round one's answers."""
    app.dependency_overrides[get_llm] = _fake_llm
    try:
        app_id = await create_scored_app()
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
        SessionLocal = await _sessionmaker()
        async with SessionLocal() as session:
            await session.execute(
                update(Application).where(Application.id == app_id).values(stage=Stage.INVITED)
            )
            await session.commit()
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})

        kit = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()["kit"]
        qid = kit["questions"][0]["id"]

        async with SessionLocal() as session:
            interviewer = User(email="reword@acme.com", role=Role.VIEWER, is_active=True)
            session.add(interviewer)
            await session.flush()
            session.add(InterviewAssignment(
                application_id=app_id, user_id=interviewer.id, round=1, track="default",
                sheet={"answers": {qid: {"answer": "said a thing", "rating": "strong"}},
                       "verdict": {"decision": "unsure", "note": None}},
                submitted_at=datetime.now(UTC),
            ))
            await session.commit()

        # Manual stage moves, mirroring _interviewed_with_panel: closes
        # round one, then reopens round two, which copies round one's
        # question ids (including `qid`) onto its own row.
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "interviewed"})
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})

        round_two = (await api_client.get(
            f"/api/applications/{app_id}/interview-kit")).json()["kit"]
        assert round_two["questions"][0]["id"] == qid, "round two lost round one's question id"

        reworded = [
            {**round_two["questions"][0], "text": "Reworded after round one closed."},
            *round_two["questions"][1:],
        ]
        resp = await api_client.patch(
            f"/api/applications/{app_id}/interview-kit", json={"questions": reworded},
        )

        assert resp.status_code == 200, resp.text
        after = (await api_client.get(
            f"/api/applications/{app_id}/interview-kit")).json()["kit"]
        assert after["questions"][0]["text"] == "Reworded after round one closed."
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_sheets_carry_their_round_so_the_ui_can_find_the_live_one(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """A recruiter sees every round's sheets, oldest first. Without a round on
    each one the UI cannot tell them apart, picks the round-1 row, and shows
    the recruiter their own already-submitted sheet with no way to record
    round-2 feedback — which also means the round can never close."""
    app.dependency_overrides[get_llm] = _fake_llm
    try:
        app_id = await create_scored_app()
        await _interviewed_with_panel(api_client, app_id)
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})

        body = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()
        rounds = sorted({s["round"] for s in body["sheets"]})

        assert rounds == [1, 2], f"sheets do not identify their round: {body['sheets']}"
        live = [s for s in body["sheets"] if s["round"] == 2]
        assert live and all(s["submitted_at"] is None for s in live), (
            "round 2's sheets should be fresh and unsubmitted"
        )
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_the_board_badge_counts_only_the_live_round(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """The kanban card shows "n/m sheets in". Counting every round makes a
    reopened two-person panel read 2/4 — as if half the round were already
    done — when round two has had nothing submitted at all."""
    app.dependency_overrides[get_llm] = _fake_llm
    try:
        app_id = await create_scored_app()
        await _interviewed_with_panel(api_client, app_id)
        job_id = (await api_client.get(f"/api/applications/{app_id}")).json()["job_id"]
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})

        board = (await api_client.get(f"/api/jobs/{job_id}/applications")).json()
        card = next(a for a in board if a["id"] == app_id)

        assert (card["sheets_total"], card["sheets_submitted"]) == (2, 0), (
            f"board badge counts earlier rounds: "
            f"{card['sheets_submitted']}/{card['sheets_total']}"
        )
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_two_simultaneous_reopens_do_not_collide(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """Reopening read-modify-writes `interview_round` and then inserts a row
    per panellist at the new round. Without a row lock two concurrent
    reopens both read round 1, both insert (app, user, 2), and the second
    hits uq_interview_assignment_app_user_round_track as an unhandled 500.
    Every other round mutation already locks for exactly this reason.
    """
    app.dependency_overrides[get_llm] = _fake_llm
    try:
        app_id = await create_scored_app()
        await _interviewed_with_panel(api_client, app_id)

        first, second = await asyncio.gather(
            api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"}),
            api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"}),
            return_exceptions=True,
        )

        codes = sorted(
            r.status_code for r in (first, second) if not isinstance(r, BaseException)
        )
        assert all(not isinstance(r, BaseException) for r in (first, second)), (
            f"a concurrent reopen raised: {first!r} {second!r}"
        )
        # One reopen succeeds; the other either also succeeds (idempotent
        # from INTERVIEWED) or is refused cleanly — never a 500.
        assert all(c < 500 for c in codes), f"concurrent reopen returned {codes}"

        SessionLocal = await _sessionmaker()
        async with SessionLocal() as session:
            rows = (await session.execute(
                select(InterviewAssignment).where(
                    InterviewAssignment.application_id == app_id)
            )).scalars().all()
        seen = [(r.user_id, r.round) for r in rows]
        assert len(seen) == len(set(seen)), f"duplicate assignment rows: {seen}"
    finally:
        app.dependency_overrides.pop(get_llm, None)
