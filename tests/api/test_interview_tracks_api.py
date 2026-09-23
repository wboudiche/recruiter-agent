"""Adding and removing a track while the interview is scheduled."""
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from recruiter.api.candidates import get_engine_dep, get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.models import Application, InterviewAssignment, InterviewTemplate, Stage
from recruiter.schemas.interview import GeneratedQuestion, GeneratedQuestions

TRACKS = "/api/applications/{}/interview-tracks"


def _db():
    return async_sessionmaker(app.dependency_overrides[get_engine_dep](), expire_on_commit=False)


async def _template(name: str, *, active: bool = True) -> int:
    async with _db()() as s:
        t = InterviewTemplate(name=name, questions=[{"id": "m1", "text": f"{name}?"}],
                              probe_mode="none", include_job_questions=False, is_active=active)
        s.add(t)
        await s.commit()
        return t.id


async def _scheduled(api_client: AsyncClient, create_scored_app) -> int:
    """An application scheduled with one default track."""
    app_id = await create_scored_app()
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
    async with _db()() as s:
        await s.execute(update(Application).where(Application.id == app_id)
                        .values(stage=Stage.INVITED))
        await s.commit()
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient(structured_responses=[
        GeneratedQuestions(questions=[GeneratedQuestion(text="A probe.", criterion="x")]),
    ])
    try:
        r = await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert r.status_code == 200, r.text
    return app_id


async def _write_draft(app_id: int, user_id: int) -> None:
    async with _db()() as s:
        await s.execute(update(InterviewAssignment).where(
            InterviewAssignment.application_id == app_id,
            InterviewAssignment.user_id == user_id,
        ).values(sheet={"answers": {}, "verdict": {"decision": None, "note": "promising"}}))
        await s.commit()


@pytest.mark.asyncio
async def test_adding_a_track_creates_and_generates_it(
    api_client: AsyncClient, create_scored_app,
) -> None:
    rh = await _template("RH screen")
    app_id = await _scheduled(api_client, create_scored_app)

    r = await api_client.post(TRACKS.format(app_id), json={"template_id": rh})

    assert r.status_code == 201, r.text
    assert [t["track"] for t in r.json()["tracks"]] == ["default", f"t{rh}"]
    tracks = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()["tracks"]
    assert tracks[1]["kit"]["status"] == "ready"
    assert [q["id"] for q in tracks[1]["kit"]["questions"]] == [f"t{rh}-m1"]


@pytest.mark.asyncio
async def test_a_track_can_only_be_added_when_it_makes_sense(
    api_client: AsyncClient, create_scored_app,
) -> None:
    rh = await _template("RH screen")
    old = await _template("Old", active=False)
    unscheduled = await create_scored_app()
    assert (await api_client.post(TRACKS.format(unscheduled),
                                  json={"template_id": rh})).status_code == 409

    app_id = await _scheduled(api_client, create_scored_app)
    old_r = await api_client.post(TRACKS.format(app_id), json={"template_id": old})
    assert old_r.status_code == 422
    rh_r = await api_client.post(TRACKS.format(app_id), json={"template_id": rh})
    assert rh_r.status_code == 201
    dup_r = await api_client.post(TRACKS.format(app_id), json={"template_id": rh})
    assert dup_r.status_code == 409
    default_r = await api_client.post(TRACKS.format(app_id), json={"template_id": None})
    assert default_r.status_code == 409, "the no-template track already exists"


@pytest.mark.asyncio
async def test_a_track_with_feedback_stays(api_client: AsyncClient, seed_tracks) -> None:
    submitted_app, _ = await seed_tracks(submitted=("rh@acme.com",))
    assert (await api_client.delete(f"{TRACKS.format(submitted_app)}/rh")).status_code == 409

    draft_app, users = await seed_tracks(panel={"tech": ["t2@acme.com"], "rh": ["r2@acme.com"]})
    await _write_draft(draft_app, users["r2@acme.com"])
    assert (await api_client.delete(f"{TRACKS.format(draft_app)}/rh")).status_code == 409


@pytest.mark.asyncio
async def test_removing_an_empty_track_takes_its_panel_with_it(
    api_client: AsyncClient, seed_tracks,
) -> None:
    app_id, _ = await seed_tracks()

    r = await api_client.delete(f"{TRACKS.format(app_id)}/rh")

    assert r.status_code == 200, r.text
    assert [t["track"] for t in r.json()["tracks"]] == ["tech"]
    async with _db()() as s:
        left = (await s.execute(select(InterviewAssignment.track).where(
            InterviewAssignment.application_id == app_id))).scalars().all()
    assert left == ["tech"]
    assert (await api_client.delete(f"{TRACKS.format(app_id)}/tech")).status_code == 409, (
        "a round keeps at least one track")
    assert (await api_client.delete(f"{TRACKS.format(app_id)}/nope")).status_code == 404


@pytest.mark.asyncio
async def test_removing_the_unstaffed_track_closes_a_finished_round(
    api_client: AsyncClient, seed_tracks,
) -> None:
    app_id, _ = await seed_tracks(panel={"tech": ["tech@acme.com"]},
                                  submitted=("tech@acme.com",))

    r = await api_client.delete(f"{TRACKS.format(app_id)}/rh")

    assert r.status_code == 200, r.text
    assert (await api_client.get(f"/api/applications/{app_id}")).json()["stage"] == "interviewed"


@pytest.mark.asyncio
async def test_a_closed_round_keeps_its_tracks(api_client: AsyncClient, seed_tracks) -> None:
    app_id, _ = await seed_tracks()
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "interviewed"})
    assert (await api_client.delete(f"{TRACKS.format(app_id)}/rh")).status_code == 409
