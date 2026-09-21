"""Templates chosen at round start, snapshotted into the round's kit."""
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from recruiter.api.candidates import get_engine_dep, get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.models import Application, InterviewKitRow, InterviewTemplate, Job, Stage
from recruiter.schemas.interview import GeneratedQuestion, GeneratedQuestions

RH = [{"id": "m1", "text": "What draws you to us?"}]


def _llm() -> FakeLLMClient:
    return FakeLLMClient(structured_responses=[GeneratedQuestions(questions=[
        GeneratedQuestion(text="A generated probe.", criterion="x"),
    ])])


async def _db():
    return async_sessionmaker(app.dependency_overrides[get_engine_dep](), expire_on_commit=False)


async def _template(name: str, *, probe_mode: str, include: bool, questions=RH,
                    active: bool = True) -> int:
    async with (await _db())() as s:
        t = InterviewTemplate(name=name, questions=questions, probe_mode=probe_mode,
                              include_job_questions=include, is_active=active)
        s.add(t)
        await s.commit()
        return t.id


async def _invited(api_client: AsyncClient, create_scored_app, *, baseline=None) -> int:
    app_id = await create_scored_app()
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
    async with (await _db())() as s:
        await s.execute(update(Application).where(Application.id == app_id)
                        .values(stage=Stage.INVITED))
        if baseline is not None:
            job_id = (await s.get(Application, app_id)).job_id
            await s.execute(update(Job).where(Job.id == job_id)
                            .values(interview_baseline=baseline))
        await s.commit()
    return app_id


async def _kits(app_id: int) -> list[InterviewKitRow]:
    async with (await _db())() as s:
        return list((await s.execute(select(InterviewKitRow)
                     .where(InterviewKitRow.application_id == app_id)
                     .order_by(InterviewKitRow.round))).scalars().all())


async def _schedule(api_client, app_id, llm, **extra):
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        return await api_client.patch(f"/api/applications/{app_id}",
                                      json={"stage": "scheduled", **extra})
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_an_rh_template_builds_a_curated_kit_with_no_llm_call(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tid = await _template("RH screen", probe_mode="none", include=False)
    app_id = await _invited(api_client, create_scored_app,
                            baseline=[{"id": "b1", "text": "Job question"}])
    llm = _llm()

    r = await _schedule(api_client, app_id, llm, interview_template_id=tid)

    assert r.status_code == 200, r.text
    assert llm.calls == [], "probe_mode none must not call the model"
    body = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()
    assert body["template_name"] == "RH screen"
    assert body["kit"]["status"] == "ready"
    assert [q["id"] for q in body["kit"]["questions"]] == [f"t{tid}-m1"]


@pytest.mark.asyncio
async def test_a_technical_template_puts_its_questions_before_the_jobs_and_adds_probes(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tid = await _template("Technical", probe_mode="score_gaps", include=True)
    app_id = await _invited(api_client, create_scored_app,
                            baseline=[{"id": "b1", "text": "Job question"}])
    llm = _llm()

    await _schedule(api_client, app_id, llm, interview_template_id=tid)

    kit = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()["kit"]
    assert [q["text"] for q in kit["questions"]] == [
        "What draws you to us?", "Job question", "A generated probe."]
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_absent_uses_the_job_default_and_null_uses_none(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tid = await _template("RH screen", probe_mode="none", include=False)
    first = await _invited(api_client, create_scored_app)
    job_id = (await api_client.get(f"/api/applications/{first}")).json()["job_id"]
    r = await api_client.patch(f"/api/jobs/{job_id}",
                               json={"default_interview_template_id": tid})
    assert r.status_code == 200, r.text

    await _schedule(api_client, first, _llm())
    assert (await _kits(first))[0].template_id == tid

    # second's job must also have the default set, or "absent" and
    # "explicit null" would be indistinguishable: both would resolve to no
    # template simply because there is no default to fall back to.
    second = await _invited(api_client, create_scored_app)
    second_job_id = (await api_client.get(f"/api/applications/{second}")).json()["job_id"]
    r = await api_client.patch(f"/api/jobs/{second_job_id}",
                               json={"default_interview_template_id": tid})
    assert r.status_code == 200, r.text
    await _schedule(api_client, second, _llm(), interview_template_id=None)
    assert (await _kits(second))[0].template_id is None


@pytest.mark.asyncio
async def test_an_archived_template_is_refused(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tid = await _template("Old", probe_mode="none", include=False, active=False)
    app_id = await _invited(api_client, create_scored_app)
    r = await _schedule(api_client, app_id, _llm(), interview_template_id=tid)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_a_template_with_any_other_stage_is_refused(
    api_client: AsyncClient, create_scored_app,
) -> None:
    app_id = await create_scored_app()
    r = await api_client.patch(f"/api/applications/{app_id}",
                               json={"stage": "validated", "interview_template_id": None})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_editing_a_template_does_not_change_a_kit_built_from_it(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tid = await _template("RH screen", probe_mode="none", include=False)
    app_id = await _invited(api_client, create_scored_app)
    await _schedule(api_client, app_id, _llm(), interview_template_id=tid)

    r = await api_client.patch(f"/api/interview-templates/{tid}",
                               json={"name": "Renamed", "questions": [{"id": "z9", "text": "New"}]})
    assert r.status_code == 200, r.text
    # Regenerate: must rebuild from the snapshot, not the edited template.
    app.dependency_overrides[get_llm] = _llm
    try:
        r = await api_client.post(f"/api/applications/{app_id}/interview-kit/generate")
        assert r.status_code == 202, r.text
    finally:
        app.dependency_overrides.pop(get_llm, None)

    body = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()
    assert [q["id"] for q in body["kit"]["questions"]] == [f"t{tid}-m1"]
    assert body["template_name"] == "RH screen", "regeneration wiped the template name"


async def _reject_and_reinvite(api_client: AsyncClient, app_id: int) -> None:
    """Move a SCHEDULED application back to INVITED in the SAME round (no
    interview happens, so no round bump): reject, unreject to scored,
    validate, then set INVITED directly in the DB — the same path
    `_invited` uses, since there is no PATCH that reaches INVITED itself
    (see `_validate_transition`: INVITED is a `_REQUIRED_PREDECESSOR`
    target reached only from the pipeline, never a stage PATCH)."""
    for stage in ("rejected", "scored", "validated"):
        r = await api_client.patch(f"/api/applications/{app_id}", json={"stage": stage})
        assert r.status_code == 200, r.text
    async with (await _db())() as s:
        await s.execute(update(Application).where(Application.id == app_id)
                        .values(stage=Stage.INVITED))
        await s.commit()


@pytest.mark.asyncio
async def test_same_round_rescheduling_with_the_same_template_keeps_its_snapshot(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """A round re-entered with the SAME template — no round bump, no sheet
    submitted — must not re-read the live template. Only a genuinely
    different template choice restamps the kit; otherwise editing a
    template between two "Mark as scheduled" clicks in the same round
    would silently rewrite the kit already built for it, contradicting
    decision 6 (a kit snapshots its template at creation)."""
    tid = await _template("RH screen", probe_mode="none", include=False)
    app_id = await _invited(api_client, create_scored_app)
    await _schedule(api_client, app_id, _llm(), interview_template_id=tid)
    before = (await _kits(app_id))[0]

    r = await api_client.patch(f"/api/interview-templates/{tid}",
                               json={"questions": [{"id": "m2", "text": "Changed"}]})
    assert r.status_code == 200, r.text
    await _reject_and_reinvite(api_client, app_id)

    r = await _schedule(api_client, app_id, _llm(), interview_template_id=tid)
    assert r.status_code == 200, r.text

    after = (await _kits(app_id))[0]
    assert after.template_snapshot == before.template_snapshot
    assert [q["id"] for q in after.questions] == [f"t{tid}-m1"], (
        "same-template rescheduling re-read the live (edited) template")


@pytest.mark.asyncio
async def test_same_round_rescheduling_with_a_different_template_restamps(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tid = await _template("RH screen", probe_mode="none", include=False)
    tid2 = await _template("Technical", probe_mode="none", include=False,
                           questions=[{"id": "k8s", "text": "Clusters?"}])
    app_id = await _invited(api_client, create_scored_app)
    await _schedule(api_client, app_id, _llm(), interview_template_id=tid)
    await _reject_and_reinvite(api_client, app_id)

    r = await _schedule(api_client, app_id, _llm(), interview_template_id=tid2)
    assert r.status_code == 200, r.text

    after = (await _kits(app_id))[0]
    assert after.template_id == tid2
    assert [q["id"] for q in after.questions] == [f"t{tid2}-k8s"], (
        "same-round rescheduling with a different template did not restamp")


async def _interview_and_close(api_client: AsyncClient, app_id: int) -> None:
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "interviewed"})


@pytest.mark.asyncio
async def test_reopening_with_the_same_template_copies_the_kit_forward(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tid = await _template("RH screen", probe_mode="none", include=False)
    app_id = await _invited(api_client, create_scored_app)
    await _schedule(api_client, app_id, _llm(), interview_template_id=tid)
    await _interview_and_close(api_client, app_id)

    # Prove the reopened round copies round 1's ACTUAL kit forward rather
    # than re-seeding from the (same) template id: edit the template
    # between rounds and hand-add a question to round 1's kit. If reopening
    # ever re-read the live template instead of copying the snapshot, both
    # the rename and the edited question list would leak into round 2, and
    # the hand-added question — never part of any template — would vanish.
    r = await api_client.patch(f"/api/interview-templates/{tid}",
                               json={"name": "Renamed",
                                     "questions": [{"id": "newq", "text": "New"}]})
    assert r.status_code == 200, r.text

    existing = (await api_client.get(
        f"/api/applications/{app_id}/interview-kit")).json()["kit"]["questions"]
    r = await api_client.patch(f"/api/applications/{app_id}/interview-kit", json={
        "questions": existing + [
            {"id": "hand1", "text": "Hand-added", "source": "baseline",
             "answer": None, "rating": None},
        ],
    })
    assert r.status_code == 200, r.text

    await _schedule(api_client, app_id, _llm(), interview_template_id=tid)

    r1, r2 = await _kits(app_id)
    assert "hand1" in [q["id"] for q in r2.questions]
    assert r2.template_id == tid and r2.template_snapshot == r1.template_snapshot
    assert [q["id"] for q in r2.questions] == [q["id"] for q in r1.questions]
    assert r2.template_name == "RH screen", (
        "reopen must copy round 1's template_name, not the live (renamed) template")
    assert not any(q["id"] == f"t{tid}-newq" for q in r2.questions), (
        "reopen re-read the live (edited) template instead of copying round 1's snapshot")


@pytest.mark.asyncio
async def test_reopening_with_a_different_template_seeds_fresh(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tech = await _template("Technical", probe_mode="none", include=False,
                           questions=[{"id": "k8s", "text": "Clusters?"}])
    rh = await _template("RH screen", probe_mode="none", include=False)
    app_id = await _invited(api_client, create_scored_app)
    await _schedule(api_client, app_id, _llm(), interview_template_id=tech)
    await _interview_and_close(api_client, app_id)

    await _schedule(api_client, app_id, _llm(), interview_template_id=rh)

    r1, r2 = await _kits(app_id)
    assert r2.template_id == rh
    assert [q["id"] for q in r2.questions] == [f"t{rh}-m1"], (
        "the RH round inherited the technical round's questions")


@pytest.mark.asyncio
async def test_with_no_templates_scheduling_is_unchanged(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """The guarantee that makes this phase safe to ship."""
    app_id = await _invited(api_client, create_scored_app,
                            baseline=[{"id": "b1", "text": "Job question"}])
    llm = _llm()

    await _schedule(api_client, app_id, llm)

    body = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()
    assert body["template_name"] is None
    assert [q["id"] for q in body["kit"]["questions"]][0] == "b1"
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_a_template_without_probes_needs_no_llm_provider(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """With no provider configured, scheduling fails a kit with "No LLM
    provider configured". A template that generates nothing must not be
    failed for want of a model it never calls. No get_llm override here:
    the fresh test database has no settings row, so get_llm_or_none
    resolves to None exactly as it does in an unconfigured install."""
    tid = await _template("RH screen", probe_mode="none", include=False)
    app_id = await _invited(api_client, create_scored_app)

    r = await api_client.patch(f"/api/applications/{app_id}",
                               json={"stage": "scheduled", "interview_template_id": tid})

    assert r.status_code == 200, r.text
    kit = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()["kit"]
    assert kit["status"] == "ready", kit.get("error")
    assert [q["id"] for q in kit["questions"]] == [f"t{tid}-m1"]
