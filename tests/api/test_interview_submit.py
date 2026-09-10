import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from recruiter.api.candidates import get_engine_dep, get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.models import Application, Candidate, Stage
from recruiter.schemas.interview import GeneratedQuestion, GeneratedQuestions


async def _create_scheduled_app(api_client: AsyncClient) -> int:
    """Create a SCHEDULED application directly via the engine."""
    job = await api_client.post("/api/jobs", json={
        "title": "Backend", "description": "x", "criteria": []
    })
    job_id = job.json()["id"]
    engine = app.dependency_overrides[get_engine_dep]()
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        c = Candidate(source_type="paste", full_name="Marie",
                      email="m@example.com")
        session.add(c)
        await session.flush()
        a = Application(job_id=job_id, candidate_id=c.id,
                        stage=Stage.SCHEDULED, score=80)
        session.add(a)
        await session.commit()
        return a.id


async def _kit_ready(api_client: AsyncClient, app_id: int) -> None:
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient(
        structured_responses=[GeneratedQuestions(questions=[
            GeneratedQuestion(text="Tell me about a production incident.",
                               criterion="reliability"),
        ])],
    )
    try:
        await api_client.post(f"/api/applications/{app_id}/interview-kit/generate")
        await api_client.patch(f"/api/applications/{app_id}/interview-kit", json={
            "questions": [{"id": "q1", "text": "Q?", "source": "probe",
                          "answer": "A"}],
        })
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_submit_advances_scheduled_to_interviewed(
    api_client: AsyncClient,
) -> None:
    app_id = await _create_scheduled_app(api_client)
    await _kit_ready(api_client, app_id)

    resp = await api_client.post(f"/api/applications/{app_id}/interview-kit/submit")
    assert resp.status_code == 200
    assert resp.json()["kit"]["submitted_at"] is not None
    app = (await api_client.get(f"/api/applications/{app_id}")).json()
    assert app["stage"] == "interviewed"


@pytest.mark.asyncio
async def test_submitting_again_does_not_advance_further(
    api_client: AsyncClient,
) -> None:
    """Editing and re-submitting after the interview must be safe."""
    app_id = await _create_scheduled_app(api_client)
    await _kit_ready(api_client, app_id)

    await api_client.post(f"/api/applications/{app_id}/interview-kit/submit")
    await api_client.post(f"/api/applications/{app_id}/interview-kit/submit")

    app = (await api_client.get(f"/api/applications/{app_id}")).json()
    assert app["stage"] == "interviewed"


@pytest.mark.asyncio
async def test_submit_with_unanswered_questions_is_allowed(
    api_client: AsyncClient,
) -> None:
    """Real interviews get cut short; blocking would encourage invented answers."""
    app_id = await _create_scheduled_app(api_client)
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient(
        structured_responses=[GeneratedQuestions(questions=[
            GeneratedQuestion(text="Tell me about a production incident.",
                               criterion="reliability"),
        ])],
    )
    try:
        await api_client.post(f"/api/applications/{app_id}/interview-kit/generate")
        await api_client.patch(f"/api/applications/{app_id}/interview-kit", json={
            "questions": [{"id": "q1", "text": "Q?", "source": "probe",
                          "answer": None}],
        })

        resp = await api_client.post(
            f"/api/applications/{app_id}/interview-kit/submit"
        )
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.pop(get_llm, None)
