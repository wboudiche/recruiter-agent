"""Starting, rescheduling and reopening a round with several tracks."""
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from recruiter.api.candidates import get_engine_dep, get_llm
from recruiter.api.interview import NO_LLM_PROVIDER
from recruiter.auth.passwords import hash_password
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.models import (
    Application,
    InterviewAssignment,
    InterviewKitRow,
    InterviewTemplate,
    Role,
    Stage,
    User,
)
from recruiter.schemas.interview import GeneratedQuestion, GeneratedQuestions


def _llm() -> FakeLLMClient:
    return FakeLLMClient(structured_responses=[GeneratedQuestions(questions=[
        GeneratedQuestion(text="A generated probe.", criterion="x"),
    ])])


def _db():
    return async_sessionmaker(app.dependency_overrides[get_engine_dep](), expire_on_commit=False)


async def _template(name: str, *, probe_mode: str = "none", include: bool = False,
                    active: bool = True) -> int:
    async with _db()() as s:
        t = InterviewTemplate(name=name, questions=[{"id": "m1", "text": f"{name}?"}],
                              probe_mode=probe_mode, include_job_questions=include,
                              is_active=active)
        s.add(t)
        await s.commit()
        return t.id


async def _invited(api_client: AsyncClient, create_scored_app) -> int:
    app_id = await create_scored_app()
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
    async with _db()() as s:
        await s.execute(update(Application).where(Application.id == app_id)
                        .values(stage=Stage.INVITED))
        await s.commit()
    return app_id


async def _schedule(api_client: AsyncClient, app_id: int, llm=None, **extra):
    if llm is not None:
        app.dependency_overrides[get_llm] = lambda: llm
    try:
        return await api_client.patch(f"/api/applications/{app_id}",
                                      json={"stage": "scheduled", **extra})
    finally:
        app.dependency_overrides.pop(get_llm, None)


async def _kits(app_id: int) -> list[InterviewKitRow]:
    async with _db()() as s:
        return list((await s.execute(select(InterviewKitRow)
                     .where(InterviewKitRow.application_id == app_id)
                     .order_by(InterviewKitRow.round, InterviewKitRow.id))).scalars().all())


async def _add_panel(app_id: int, *, track: str, email: str, round_number: int = 1,
                     sheet: dict | None = None) -> int:
    async with _db()() as s:
        u = User(email=email, role=Role.VIEWER, is_active=True, password_hash=hash_password("x"))
        s.add(u)
        await s.flush()
        row = InterviewAssignment(application_id=app_id, user_id=u.id, round=round_number,
                                  track=track)
        if sheet is not None:
            row.sheet = sheet
        s.add(row)
        await s.commit()
        return u.id


async def _panel(app_id: int, round_number: int) -> list[tuple[int, str]]:
    async with _db()() as s:
        rows = (await s.execute(select(InterviewAssignment).where(
            InterviewAssignment.application_id == app_id,
            InterviewAssignment.round == round_number,
        ).order_by(InterviewAssignment.id))).scalars().all()
        return [(r.user_id, r.track) for r in rows]


async def _reject_and_reinvite(api_client: AsyncClient, app_id: int) -> None:
    """Back to INVITED in the SAME round: reject, unreject, validate, then
    set INVITED in the DB (the API has no "invited" stage literal)."""
    for stage in ("rejected", "scored", "validated"):
        r = await api_client.patch(f"/api/applications/{app_id}", json={"stage": stage})
        assert r.status_code == 200, r.text
    async with _db()() as s:
        await s.execute(update(Application).where(Application.id == app_id)
                        .values(stage=Stage.INVITED))
        await s.commit()


@pytest.mark.asyncio
async def test_scheduling_two_templates_makes_two_tracks(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tech = await _template("Technical", probe_mode="score_gaps", include=True)
    rh = await _template("RH screen")
    app_id = await _invited(api_client, create_scored_app)
    llm = _llm()

    r = await _schedule(api_client, app_id, llm, interview_template_ids=[tech, rh])

    assert r.status_code == 200, r.text
    kits = await _kits(app_id)
    assert [k.track for k in kits] == [f"t{tech}", f"t{rh}"]
    assert [k.status for k in kits] == ["ready", "ready"]
    assert len(llm.calls) == 1, "only the score-gap track calls the model"


@pytest.mark.asyncio
async def test_track_choices_are_validated(api_client: AsyncClient, create_scored_app) -> None:
    rh = await _template("RH screen")
    old = await _template("Old", active=False)
    app_id = await _invited(api_client, create_scored_app)

    for body in ({"interview_template_ids": [rh], "interview_template_id": rh},
                 {"interview_template_ids": []},
                 {"interview_template_ids": [old]}):
        assert (await _schedule(api_client, app_id, _llm(), **body)).status_code == 422, body

    other = await create_scored_app()
    r = await api_client.patch(f"/api/applications/{other}",
                               json={"stage": "validated", "interview_template_ids": [rh]})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_duplicate_choices_make_one_track_each(
    api_client: AsyncClient, create_scored_app,
) -> None:
    rh = await _template("RH screen")
    app_id = await _invited(api_client, create_scored_app)

    r = await _schedule(api_client, app_id, _llm(), interview_template_ids=[rh, rh, None, None])

    assert r.status_code == 200, r.text
    assert [k.track for k in await _kits(app_id)] == [f"t{rh}", "default"]


@pytest.mark.asyncio
async def test_without_a_provider_only_the_track_that_needs_one_fails(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tech = await _template("Technical", probe_mode="score_gaps", include=True)
    rh = await _template("RH screen")
    app_id = await _invited(api_client, create_scored_app)

    r = await _schedule(api_client, app_id, interview_template_ids=[tech, rh])

    assert r.status_code == 200, r.text
    by_track = {k.track: k for k in await _kits(app_id)}
    assert (by_track[f"t{tech}"].status, by_track[f"t{tech}"].error) == ("error", NO_LLM_PROVIDER)
    assert by_track[f"t{rh}"].status == "ready"


@pytest.mark.asyncio
async def test_scheduling_the_same_round_again_reconciles_its_tracks(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tech = await _template("Technical")
    rh = await _template("RH screen")
    culture = await _template("Culture")
    app_id = await _invited(api_client, create_scored_app)
    await _schedule(api_client, app_id, interview_template_ids=[tech, rh])
    await _add_panel(app_id, track=f"t{tech}", email="alice@acme.com")
    await _add_panel(app_id, track=f"t{rh}", email="carol@acme.com",
                     sheet={"answers": {}, "verdict": {"decision": None, "note": "promising"}})
    await _reject_and_reinvite(api_client, app_id)

    r = await _schedule(api_client, app_id, interview_template_ids=[culture])

    assert r.status_code == 200, r.text
    assert [k.track for k in await _kits(app_id)] == [f"t{rh}", f"t{culture}"], (
        "Technical was unticked and empty: removed with its panel; RH has a draft: kept")
    assert [t for _, t in await _panel(app_id, 1)] == [f"t{rh}"]


@pytest.mark.asyncio
async def test_another_round_copies_chosen_tracks_and_starts_new_ones(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tech = await _template("Technical")
    rh = await _template("RH screen")
    culture = await _template("Culture")
    app_id = await _invited(api_client, create_scored_app)
    await _schedule(api_client, app_id, interview_template_ids=[tech, rh])
    alice = await _add_panel(app_id, track=f"t{tech}", email="alice@acme.com")
    await _add_panel(app_id, track=f"t{rh}", email="carol@acme.com")
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "interviewed"})

    r = await _schedule(api_client, app_id, interview_template_ids=[tech, culture])

    assert r.status_code == 200, r.text
    kits = await _kits(app_id)
    round_one = {k.track: k for k in kits if k.round == 1}
    round_two = [k for k in kits if k.round == 2]
    assert [k.track for k in round_two] == [f"t{tech}", f"t{culture}"]
    assert round_two[0].questions == round_one[f"t{tech}"].questions
    assert round_two[0].template_snapshot == round_one[f"t{tech}"].template_snapshot
    assert await _panel(app_id, 2) == [(alice, f"t{tech}")], (
        "only a copied track brings its panel; RH stays in round one")


@pytest.mark.asyncio
async def test_interviewers_picked_before_scheduling_join_the_first_track(
    api_client: AsyncClient, create_scored_app,
) -> None:
    rh = await _template("RH screen")
    app_id = await _invited(api_client, create_scored_app)
    early = await _add_panel(app_id, track="default", email="early@acme.com")

    await _schedule(api_client, app_id, interview_template_ids=[rh])

    assert await _panel(app_id, 1) == [(early, f"t{rh}")]
