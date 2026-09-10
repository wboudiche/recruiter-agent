import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.candidates import get_llm
from recruiter.auth.passwords import hash_password
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.models import Application, Candidate, Job, Role, Stage, User
from recruiter.schemas.interview import GeneratedQuestion, GeneratedQuestions


@pytest.mark.asyncio
async def test_get_returns_null_kit_before_generation(
    api_client: AsyncClient, create_scored_app,
) -> None:
    app_id = await create_scored_app()
    resp = await api_client.get(f"/api/applications/{app_id}/interview-kit")
    assert resp.status_code == 200
    assert resp.json()["kit"] is None


@pytest.mark.asyncio
async def test_generate_returns_202_and_kit_is_no_longer_null(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """202 because the model call runs in the background — the request must
    not block on it, and must not fail because of it.

    FastAPI's BackgroundTasks run to completion before the in-process
    ASGI transport used by `api_client` hands control back to the test
    (there is no separate worker), so by the time the follow-up GET runs
    the background task has already resolved the kit to its final state.
    What matters here is the contract the docstring above describes: the
    POST itself returns 202 without waiting on the model, and the kit
    lands in a terminal, non-null state without the request ever
    touching the LLM directly.
    """
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient(
        structured_responses=[GeneratedQuestions(questions=[
            GeneratedQuestion(text="Tell me about a production incident.",
                               criterion="reliability"),
        ])],
    )
    try:
        app_id = await create_scored_app()
        resp = await api_client.post(f"/api/applications/{app_id}/interview-kit/generate")
        assert resp.status_code == 202

        kit = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()["kit"]
        assert kit["status"] in {"generating", "ready"}
        if kit["status"] == "ready":
            assert kit["generated_at"] is not None
            assert any(q["source"] == "probe" for q in kit["questions"])
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_generate_404s_for_an_unknown_application(api_client: AsyncClient) -> None:
    # FastAPI resolves get_llm before the handler runs (same as re-enrich);
    # provide a fake so the request reaches the handler's 404 check.
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()
    try:
        resp = await api_client.post("/api/applications/999999/interview-kit/generate")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_llm, None)


# --- Viewer policy: the app-wide default-deny guard (see
# tests/api/test_viewer_matrix.py), not a route-local `require_role`, is
# what keeps a viewer out of `/interview-kit/generate`. This mirrors that
# file's `_add`/`_login` pattern rather than importing it (`tests` isn't
# an importable package in this repo — see the conftest fixture change
# in this same task for the same constraint).

async def _add(session: AsyncSession, email: str, role: Role) -> User:
    user = User(email=email, role=role, is_active=True,
                password_hash=hash_password("pw-12345678"))
    session.add(user)
    await session.commit()
    return user


async def _login(client: AsyncClient, email: str) -> None:
    r = await client.post("/api/auth/login/password",
                           json={"email": email, "password": "pw-12345678"})
    assert r.status_code == 204


async def _seed_application(session: AsyncSession) -> int:
    job = Job(title="Backend", description="x", criteria=[])
    session.add(job)
    await session.flush()
    candidate = Candidate(source_type="paste", full_name="Marie", email="m@example.com")
    session.add(candidate)
    await session.flush()
    app_row = Application(job_id=job.id, candidate_id=candidate.id, stage=Stage.SCORED, score=80)
    session.add(app_row)
    await session.commit()
    return app_row.id


@pytest.mark.asyncio
async def test_viewer_is_refused_generate_but_allowed_get(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    """The endpoints carry no `require_role` of their own — the app-wide
    `viewer_readonly_guard` (deps.py) already default-denies every
    mutating method to viewers, and neither interview-kit route is on
    `VIEWER_ALLOWED_ROUTES`. This asserts that policy actually holds for
    this router: generate is refused, read is not."""
    app_id = await _seed_application(db_session_with_schema)
    await _add(db_session_with_schema, "viewer@acme.com", Role.VIEWER)
    await _login(api_client_unauth, "viewer@acme.com")

    generate = await api_client_unauth.post(
        f"/api/applications/{app_id}/interview-kit/generate"
    )
    assert generate.status_code == 403

    read = await api_client_unauth.get(f"/api/applications/{app_id}/interview-kit")
    assert read.status_code == 200
    assert read.json()["kit"] is None


@pytest.mark.asyncio
async def test_patch_stores_answers_and_ratings(
    api_client: AsyncClient, create_scored_app,
) -> None:
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient(
        structured_responses=[GeneratedQuestions(questions=[
            GeneratedQuestion(text="Tell me about a production incident.",
                               criterion="reliability"),
        ])],
    )
    try:
        app_id = await create_scored_app()
        await api_client.post(f"/api/applications/{app_id}/interview-kit/generate")

        body = {"questions": [
            {"id": "q1", "text": "Describe an incident.", "source": "probe",
             "answer": "Handled an etcd outage", "rating": "strong"},
        ]}
        resp = await api_client.patch(
            f"/api/applications/{app_id}/interview-kit", json=body
        )
        assert resp.status_code == 200
        q = resp.json()["kit"]["questions"][0]
        assert q["answer"] == "Handled an etcd outage"
        assert q["rating"] == "strong"
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_patch_rejects_duplicate_question_ids(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """Ids address questions; duplicates make an edit ambiguous."""
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient(
        structured_responses=[GeneratedQuestions(questions=[
            GeneratedQuestion(text="Tell me about a production incident.",
                               criterion="reliability"),
        ])],
    )
    try:
        app_id = await create_scored_app()
        await api_client.post(f"/api/applications/{app_id}/interview-kit/generate")
        body = {"questions": [
            {"id": "same", "text": "One", "source": "probe"},
            {"id": "same", "text": "Two", "source": "probe"},
        ]}
        resp = await api_client.patch(
            f"/api/applications/{app_id}/interview-kit", json=body
        )
        assert resp.status_code == 422
        assert "duplicate" in resp.text.lower()
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_patch_404s_when_no_kit_exists(
    api_client: AsyncClient, create_scored_app,
) -> None:
    app_id = await create_scored_app()
    resp = await api_client.patch(f"/api/applications/{app_id}/interview-kit",
                                  json={"questions": []})
    assert resp.status_code == 404
