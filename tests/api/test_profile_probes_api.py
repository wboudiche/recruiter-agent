"""An RH round's probes come from the candidate's history (phase 4).

`probe_mode: "profile"` swaps the technical generator for one that reads
the candidate's own path and what enrichment found, and never sees the
score breakdown.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from recruiter.api.candidates import get_engine_dep, get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.models import (
    Application,
    Candidate,
    InterviewKitRow,
    InterviewTemplate,
    Job,
    Stage,
)
from recruiter.pipeline.interview_kit_generator import _PROFILE_DRAFT_SYSTEM
from recruiter.schemas.interview import GeneratedQuestion, GeneratedQuestions

KIT = "/api/applications/{}/interview-kit"


def _db():
    return async_sessionmaker(app.dependency_overrides[get_engine_dep](), expire_on_commit=False)


def _llm(*questions: str) -> FakeLLMClient:
    return FakeLLMClient(structured_responses=[GeneratedQuestions(questions=[
        GeneratedQuestion(text=text, criterion="moves") for text in questions
    ])])


async def _profile_template(name: str = "RH screen", *, probe_mode: str = "profile") -> int:
    async with _db()() as s:
        template = InterviewTemplate(
            name=name, questions=[{"id": "m1", "text": "What draws you to us?"}],
            probe_mode=probe_mode, include_job_questions=False,
        )
        s.add(template)
        await s.commit()
        return template.id


async def _with_history(app_id: int) -> None:
    """Give the candidate a history worth asking about, and the application
    a score breakdown the RH prompt must ignore."""
    async with _db()() as s:
        app_row = await s.get(Application, app_id)
        candidate = await s.get(Candidate, app_row.candidate_id)
        candidate.headline = "Staff SRE"
        candidate.experience = [{
            "title": "Staff SRE", "company": "Acme", "start": "2024", "end": "2025",
            "description": "Owned the cluster migration.",
        }]
        app_row.enrichment = {"results": [{
            "source": "github", "profile_url": "https://github.com/x", "confidence": 0.9,
            "discovered": False, "signals": [],
            "summary": "Maintains a Terraform provider with 400 stars.",
        }]}
        app_row.score_breakdown = [{
            "criterion": "Kubernetes", "weight": 0.4, "score": 40,
            "rationale": "no evidence of production-grade clusters",
        }]
        await s.commit()


async def _invited(api_client: AsyncClient, create_scored_app) -> int:
    app_id = await create_scored_app()
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
    async with _db()() as s:
        await s.execute(update(Application).where(Application.id == app_id)
                        .values(stage=Stage.INVITED))
        await s.commit()
    return app_id


async def _schedule(api_client: AsyncClient, app_id: int, llm: FakeLLMClient, template_id: int):
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        return await api_client.patch(
            f"/api/applications/{app_id}",
            json={"stage": "scheduled", "interview_template_ids": [template_id]},
        )
    finally:
        app.dependency_overrides.pop(get_llm, None)


async def _kit(app_id: int) -> InterviewKitRow:
    async with _db()() as s:
        return (await s.execute(select(InterviewKitRow).where(
            InterviewKitRow.application_id == app_id,
        ))).scalar_one()


@pytest.mark.asyncio
async def test_an_rh_round_asks_about_the_candidates_path(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tid = await _profile_template()
    app_id = await _invited(api_client, create_scored_app)
    await _with_history(app_id)
    llm = _llm("What made you leave Acme after a year?")

    r = await _schedule(api_client, app_id, llm, tid)

    assert r.status_code == 200, r.text
    kit = (await api_client.get(KIT.format(app_id))).json()["kit"]
    assert kit["status"] == "ready"
    assert [q["text"] for q in kit["questions"]] == [
        "What draws you to us?", "What made you leave Acme after a year?"]
    prompt = "\n".join(m.content for call in llm.calls for m in call.get("messages", []))
    assert "Owned the cluster migration" in prompt
    assert "Terraform provider with 400 stars" in prompt
    assert "production-grade clusters" not in prompt, (
        "the RH prompt must not carry the technical score breakdown")


@pytest.mark.asyncio
async def test_a_thin_profile_leaves_the_curated_questions_alone(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """Nothing to ask about is not a failure: the model returns no probes
    and the kit is ready with the template's own questions."""
    tid = await _profile_template()
    app_id = await _invited(api_client, create_scored_app)
    llm = _llm()

    r = await _schedule(api_client, app_id, llm, tid)

    assert r.status_code == 200, r.text
    kit = await _kit(app_id)
    assert kit.status == "ready"
    assert kit.error is None
    assert [q["text"] for q in kit.questions] == ["What draws you to us?"]


@pytest.mark.asyncio
async def test_drafting_on_an_rh_track_stays_in_the_same_register(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """"Draft with AI" on a profile track must not fall back to the
    technical prompt — that would put a scoring question in an RH kit."""
    tid = await _profile_template()
    app_id = await _invited(api_client, create_scored_app)
    await _with_history(app_id)
    await _schedule(api_client, app_id, _llm(), tid)

    llm = _llm("Where do you want to be in three years?")
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        r = await api_client.post(f"{KIT.format(app_id)}/draft-question", json={"hint": None})
    finally:
        app.dependency_overrides.pop(get_llm, None)

    assert r.status_code == 200, r.text
    assert r.json()["question"]["text"] == "Where do you want to be in three years?"
    call = llm.calls[0]
    assert call["system"] == _PROFILE_DRAFT_SYSTEM, "the register is the point of the branch"
    assert "Owned the cluster migration" in call["messages"][0].content
    assert "production-grade clusters" not in call["messages"][0].content


@pytest.mark.asyncio
async def test_drafting_on_a_curated_rh_track_stays_in_the_same_register(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """An RH template that generates no probes at all (`none`) is still an
    RH interview: drafting one question by hand must not reach for the
    technical prompt and its score breakdown."""
    tid = await _profile_template(probe_mode="none")
    app_id = await _invited(api_client, create_scored_app)
    await _with_history(app_id)
    await _schedule(api_client, app_id, _llm(), tid)

    llm = _llm("What pulled you towards this team?")
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        r = await api_client.post(f"{KIT.format(app_id)}/draft-question", json={"hint": None})
    finally:
        app.dependency_overrides.pop(get_llm, None)

    assert r.status_code == 200, r.text
    call = llm.calls[0]
    assert call["system"] == _PROFILE_DRAFT_SYSTEM, "a curated RH track drafted technically"
    assert "production-grade clusters" not in call["messages"][0].content


@pytest.mark.asyncio
async def test_a_malformed_candidate_still_answers_with_the_draft_error(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """Building the profile is part of drafting, so a candidate record that
    cannot be rendered belongs in the handler's 502, not in a bare 500."""
    tid = await _profile_template()
    app_id = await _invited(api_client, create_scored_app)
    await _schedule(api_client, app_id, _llm(), tid)
    async with _db()() as s:
        app_row = await s.get(Application, app_id)
        candidate = await s.get(Candidate, app_row.candidate_id)
        candidate.experience = ["a string where the extractor writes an object"]
        await s.commit()

    app.dependency_overrides[get_llm] = lambda: _llm("unused")
    try:
        r = await api_client.post(f"{KIT.format(app_id)}/draft-question", json={"hint": None})
    finally:
        app.dependency_overrides.pop(get_llm, None)

    assert r.status_code == 502, r.text
    assert "Could not draft a question" in r.json()["detail"]


async def _describe_job(app_id: int, title: str, description: str) -> None:
    async with _db()() as s:
        app_row = await s.get(Application, app_id)
        job = await s.get(Job, app_row.job_id)
        job.title = title
        job.description = description
        await s.commit()


@pytest.mark.asyncio
async def test_an_rh_round_knows_which_role_the_candidate_applied_for(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """Blind to the scoring, not to the job: without the role an RH question
    cannot ask why this move, only generic ones about the past."""
    tid = await _profile_template()
    app_id = await _invited(api_client, create_scored_app)
    await _with_history(app_id)
    await _describe_job(app_id, "Head of Platform", "Leads a platform team of twelve, in Paris.")
    llm = _llm("Why move from owning a migration to leading a team?")

    r = await _schedule(api_client, app_id, llm, tid)

    assert r.status_code == 200, r.text
    prompt = llm.calls[0]["messages"][0].content
    assert "Head of Platform" in prompt
    assert "team of twelve" in prompt
    assert "Owned the cluster migration" in prompt, "the history is still what it asks about"
    assert "production-grade clusters" not in prompt, "the scoring stays out"


@pytest.mark.asyncio
async def test_drafting_on_an_rh_track_knows_the_role_too(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tid = await _profile_template()
    app_id = await _invited(api_client, create_scored_app)
    await _with_history(app_id)
    await _describe_job(app_id, "Head of Platform", "Leads a platform team of twelve, in Paris.")
    await _schedule(api_client, app_id, _llm(), tid)

    llm = _llm("How big a team have you run?")
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        r = await api_client.post(f"{KIT.format(app_id)}/draft-question", json={"hint": None})
    finally:
        app.dependency_overrides.pop(get_llm, None)

    assert r.status_code == 200, r.text
    prompt = llm.calls[0]["messages"][0].content
    assert "Head of Platform" in prompt
    assert "team of twelve" in prompt, "the drafting path carries the description too"
    assert "production-grade clusters" not in prompt
