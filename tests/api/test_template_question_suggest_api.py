import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.candidates import get_llm
from recruiter.auth.passwords import hash_password
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.models import Role, User
from recruiter.schemas.interview_template import (
    SuggestedTemplateQuestion,
    SuggestedTemplateQuestions,
)

URL = "/api/interview-templates/suggest-questions"
BODY = {"name": "Technical — Data Science", "description": "Modelling and MLOps",
        "kind": "technical"}
PW = "pw-12345678"


def _six() -> SuggestedTemplateQuestions:
    return SuggestedTemplateQuestions(questions=[
        SuggestedTemplateQuestion(text=f"Question {i}", criterion="modelling") for i in range(6)
    ])


@pytest.fixture
def fake():
    llm = FakeLLMClient(structured_responses=[_six()])
    app.dependency_overrides[get_llm] = lambda: llm
    yield llm
    app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_suggests_questions(api_client: AsyncClient, fake: FakeLLMClient) -> None:
    resp = await api_client.post(URL, json=BODY)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["questions"]) == 6
    assert body["questions"][0] == {"text": "Question 0", "criterion": "modelling"}


@pytest.mark.asyncio
async def test_uses_the_chosen_job(api_client: AsyncClient, fake: FakeLLMClient) -> None:
    job = (await api_client.post("/api/jobs", json={
        "title": "Data Scientist", "description": "Build churn models", "criteria": [],
    })).json()
    resp = await api_client.post(URL, json={**BODY, "job_id": job["id"]})
    assert resp.status_code == 200, resp.text
    assert job["title"] in fake.calls[-1]["messages"][0].content


@pytest.mark.asyncio
async def test_unknown_job_is_404(api_client: AsyncClient, fake: FakeLLMClient) -> None:
    resp = await api_client.post(URL, json={**BODY, "job_id": 999999})
    assert resp.status_code == 404
    assert fake.calls == []


@pytest.mark.asyncio
async def test_llm_failure_is_502(api_client: AsyncClient) -> None:
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()
    try:
        resp = await api_client.post(URL, json=BODY)
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert resp.status_code == 502
    assert resp.json()["detail"] == "Question suggestion failed"


@pytest.mark.asyncio
async def test_writes_nothing(api_client: AsyncClient, fake: FakeLLMClient) -> None:
    before = (await api_client.get("/api/interview-templates?include_archived=true")).json()
    assert (await api_client.post(URL, json=BODY)).status_code == 200
    after = (await api_client.get("/api/interview-templates?include_archived=true")).json()
    assert after == before


@pytest.mark.asyncio
async def test_bad_kind_is_422(api_client: AsyncClient, fake: FakeLLMClient) -> None:
    assert (await api_client.post(URL, json={**BODY, "kind": "design"})).status_code == 422


@pytest.fixture
def _reset_limiter():
    from recruiter.api.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


@pytest.mark.asyncio
async def test_viewers_cannot_suggest(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
    fake: FakeLLMClient, _reset_limiter,
) -> None:
    db_session_with_schema.add(User(email="view@acme.com", role=Role.VIEWER, is_active=True,
                                    password_hash=hash_password(PW)))
    await db_session_with_schema.commit()
    login = await api_client_unauth.post("/api/auth/login/password",
                                         json={"email": "view@acme.com", "password": PW})
    assert login.status_code == 204
    assert (await api_client_unauth.post(URL, json=BODY)).status_code == 403
    assert fake.calls == []


@pytest.mark.asyncio
async def test_a_long_existing_list_is_trimmed_not_refused(
    api_client: AsyncClient, fake: FakeLLMClient,
) -> None:
    existing = [f"Old question {i}" for i in range(60)] + ["x" * 3000]
    resp = await api_client.post(URL, json={**BODY, "existing": existing})
    assert resp.status_code == 200, resp.text
    prompt = fake.calls[-1]["messages"][0].content
    assert "x" * 2000 in prompt and "x" * 2001 not in prompt  # each item capped
    assert "Old question 59" in prompt          # the most recent items are kept
    assert "Old question 0\n" not in prompt     # the oldest beyond 50 are dropped
