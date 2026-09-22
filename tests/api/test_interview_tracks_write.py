"""Writing to one track of a two-track round (phase 3)."""
import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from recruiter.api.candidates import get_engine_dep, get_llm
from recruiter.api.interview import run_generate_kit
from recruiter.events import EventBus
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.models import InterviewAssignment, InterviewKitRow
from recruiter.schemas.interview import GeneratedQuestion, GeneratedQuestions

KIT = "/api/applications/{}/interview-kit"


def _q(qid: str, text: str) -> dict:
    return {"id": qid, "text": text, "source": "baseline"}


@pytest.fixture(autouse=True)
def _reset_limiter():
    from recruiter.api.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


def _db():
    return async_sessionmaker(app.dependency_overrides[get_engine_dep](), expire_on_commit=False)


async def _kit(app_id: int, track: str) -> InterviewKitRow | None:
    async with _db()() as s:
        return (await s.execute(select(InterviewKitRow).where(
            InterviewKitRow.application_id == app_id, InterviewKitRow.track == track,
        ))).scalar_one_or_none()


async def _row(app_id: int, user_id: int) -> InterviewAssignment:
    async with _db()() as s:
        return (await s.execute(select(InterviewAssignment).where(
            InterviewAssignment.application_id == app_id,
            InterviewAssignment.user_id == user_id,
        ))).scalar_one()


@pytest.mark.asyncio
async def test_a_recruiter_edits_one_named_track(api_client: AsyncClient, seed_tracks) -> None:
    app_id, _ = await seed_tracks()
    body = {"questions": [_q("r1", "rh question"), _q("r2", "Why us?")]}

    assert (await api_client.patch(KIT.format(app_id), json=body)).status_code == 422, (
        "two tracks: the recruiter must name one")
    r = await api_client.patch(f"{KIT.format(app_id)}?track=rh", json=body)

    assert r.status_code == 200, r.text
    assert [q["id"] for q in (await _kit(app_id, "rh")).questions] == ["r1", "r2"]
    assert [q["id"] for q in (await _kit(app_id, "tech")).questions] == ["q1"]


@pytest.mark.asyncio
async def test_an_interviewer_appends_to_their_own_track_only(
    api_client_unauth: AsyncClient, seed_tracks, login_as,
) -> None:
    app_id, _ = await seed_tracks()
    await login_as(api_client_unauth, "rh@acme.com")
    body = {"questions": [_q("r1", "rh question"), _q("r2", "Why us?")]}

    assert (await api_client_unauth.patch(KIT.format(app_id), json=body)).status_code == 200
    assert (await api_client_unauth.patch(
        f"{KIT.format(app_id)}?track=tech",
        json={"questions": [_q("q1", "tech question"), _q("q2", "More?")]},
    )).status_code == 403


@pytest.mark.asyncio
async def test_the_freeze_is_per_track(api_client: AsyncClient, seed_tracks) -> None:
    app_id, _ = await seed_tracks(submitted=("rh@acme.com",))

    assert (await api_client.patch(
        f"{KIT.format(app_id)}?track=tech", json={"questions": []},
    )).status_code == 200, "Technical has no submitted sheet: still editable"
    assert (await api_client.patch(
        f"{KIT.format(app_id)}?track=rh", json={"questions": []},
    )).status_code == 409, "RH is frozen by its submitted sheet"
    # generate depends on get_llm, which 503s without a provider before the
    # handler could answer 409 — give it one.
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()
    try:
        r = await api_client.post(f"{KIT.format(app_id)}/generate?track=rh")
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_generate_names_its_track(api_client: AsyncClient, seed_tracks) -> None:
    app_id, _ = await seed_tracks()
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient(structured_responses=[
        GeneratedQuestions(questions=[GeneratedQuestion(text="A probe.", criterion="x")]),
    ])
    try:
        assert (await api_client.post(f"{KIT.format(app_id)}/generate")).status_code == 422
        r = await api_client.post(f"{KIT.format(app_id)}/generate?track=tech")
    finally:
        app.dependency_overrides.pop(get_llm, None)

    assert r.status_code == 202, r.text
    assert "A probe." in [q["text"] for q in (await _kit(app_id, "tech")).questions]
    assert [q["id"] for q in (await _kit(app_id, "rh")).questions] == ["r1"]


@pytest.mark.asyncio
async def test_a_sheet_lands_on_the_callers_track(
    api_client_unauth: AsyncClient, seed_tracks, login_as,
) -> None:
    app_id, users = await seed_tracks()
    await login_as(api_client_unauth, "rh@acme.com")
    sheet = {"answers": {"r1": {"answer": "Loves it", "rating": "strong"},
                         "q1": {"answer": "not my track", "rating": None}},
             "verdict": {"decision": None, "note": None}}

    r = await api_client_unauth.patch(f"{KIT.format(app_id)}/sheet", json=sheet)
    assert r.status_code == 200, r.text
    saved = (await _row(app_id, users["rh@acme.com"])).sheet
    assert list(saved["answers"]) == ["r1"], "answers are pruned to the caller's track"

    assert (await api_client_unauth.patch(
        f"{KIT.format(app_id)}/sheet?track=tech", json=sheet,
    )).status_code == 409


@pytest.mark.asyncio
async def test_a_recruiter_can_take_an_unstaffed_track(
    api_client: AsyncClient, seed_tracks,
) -> None:
    app_id, _ = await seed_tracks(panel={"tech": ["tech@acme.com"]})
    sheet = {"answers": {}, "verdict": {"decision": None, "note": "fine"}}

    assert (await api_client.patch(f"{KIT.format(app_id)}/sheet", json=sheet)).status_code == 422
    r = await api_client.patch(f"{KIT.format(app_id)}/sheet?track=rh", json=sheet)
    assert r.status_code == 200, r.text
    tracks = sorted(s["track"] for s in r.json()["sheets"])
    assert tracks == ["rh", "tech"]


@pytest.mark.asyncio
async def test_generation_abandons_a_track_removed_meanwhile(
    api_client: AsyncClient, seed_tracks,
) -> None:
    app_id, _ = await seed_tracks()
    async with _db()() as s:
        await s.execute(update(InterviewKitRow).where(
            InterviewKitRow.application_id == app_id, InterviewKitRow.track == "tech",
        ).values(status="generating"))
        await s.commit()

    class _RemovesTrackMidCall:
        """Removes the track from another session while the model 'thinks',
        like a recruiter clicking Remove track mid-generation (same shape as
        test_interview_rounds.py's _BumpsRoundMidCall)."""

        async def chat_structured(self, *a: object, **kw: object) -> GeneratedQuestions:
            async with _db()() as other:
                await other.execute(delete(InterviewAssignment).where(
                    InterviewAssignment.application_id == app_id,
                    InterviewAssignment.track == "tech"))
                await other.execute(delete(InterviewKitRow).where(
                    InterviewKitRow.application_id == app_id, InterviewKitRow.track == "tech"))
                await other.commit()
            return GeneratedQuestions(questions=[GeneratedQuestion(text="Late.", criterion="x")])

    await run_generate_kit(
        application_id=app_id, track="tech", engine=app.dependency_overrides[get_engine_dep](),
        llm=_RemovesTrackMidCall(), bus=EventBus(),
    )

    assert await _kit(app_id, "tech") is None, "generation resurrected a removed track"
