import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.candidates import get_llm
from recruiter.auth.passwords import hash_password
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.models import Application, Candidate, InterviewAssignment, Job, Role, Stage, User

PW = "pw-12345678"
Q1 = {"id": "q1", "text": "Why?", "source": "probe"}
Q2 = {"id": "q2", "text": "How?", "source": "probe"}


@pytest.fixture(autouse=True)
def _reset_limiter():
    # This module logs several users in and out per test; without a reset
    # the shared 5/min login budget (see rate_limit.py) trips across tests
    # — and across files, since the in-memory store is process-wide. Same
    # pattern as test_viewer_matrix.py and test_interview_sheets_api.py.
    from recruiter.api.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


async def _add(session: AsyncSession, email: str, role: Role) -> User:
    user = User(email=email, role=role, is_active=True, password_hash=hash_password(PW))
    session.add(user)
    await session.commit()
    return user


async def _login(client: AsyncClient, email: str) -> None:
    await client.post("/api/auth/logout")
    r = await client.post("/api/auth/login/password", json={"email": email, "password": PW})
    assert r.status_code == 204


async def _seed(session: AsyncSession) -> int:
    job = Job(title="Backend", description="x", criteria=[])
    session.add(job)
    await session.flush()
    cand = Candidate(source_type="paste", full_name="Marie", email="m@example.com")
    session.add(cand)
    await session.flush()
    app_row = Application(job_id=job.id, candidate_id=cand.id, stage=Stage.SCHEDULED, score=80,
                          interview_kit={"status": "ready", "questions": [Q1, Q2]})
    session.add(app_row)
    await session.commit()
    return app_row.id


@pytest.mark.asyncio
async def test_removal_and_regenerate_are_refused_after_first_submit(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_id = await _seed(db_session_with_schema)
    a = await _add(db_session_with_schema, "a@acme.com", Role.VIEWER)
    await _add(db_session_with_schema, "rec@acme.com", Role.RECRUITER)
    db_session_with_schema.add(InterviewAssignment(application_id=app_id, user_id=a.id))
    await db_session_with_schema.commit()
    kit = f"/api/applications/{app_id}/interview-kit"

    await _login(api_client_unauth, "a@acme.com")
    assert (await api_client_unauth.post(f"{kit}/sheet/submit")).status_code == 200

    await _login(api_client_unauth, "rec@acme.com")
    r = await api_client_unauth.patch(kit, json={"questions": [Q1]})
    assert r.status_code == 409
    # Renaming keeps ids, so it is still allowed.
    r = await api_client_unauth.patch(kit, json={"questions": [{**Q1, "text": "Why us?"}, Q2]})
    assert r.status_code == 200
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()
    try:
        assert (await api_client_unauth.post(f"{kit}/generate")).status_code == 409
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_a_question_with_a_submitted_answer_cannot_be_reworded(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    """A submitted answer is a record of what was asked and what was said.
    Rewording the question afterwards changes what that record means, which
    matters the moment a hiring decision is questioned.

    Scoped to questions that were actually answered: an untouched question
    stays freely editable, so fixing a typo after one interview — the case
    the design deliberately protected — still works.
    """
    app_id = await _seed(db_session_with_schema)
    a = await _add(db_session_with_schema, "a@acme.com", Role.VIEWER)
    await _add(db_session_with_schema, "rec@acme.com", Role.RECRUITER)
    db_session_with_schema.add(InterviewAssignment(application_id=app_id, user_id=a.id))
    await db_session_with_schema.commit()
    kit = f"/api/applications/{app_id}/interview-kit"

    await _login(api_client_unauth, "a@acme.com")
    await api_client_unauth.patch(f"{kit}/sheet", json={
        "answers": {"q1": {"answer": "Because scale.", "rating": "strong"}},
        "verdict": {"decision": None, "note": None},
    })
    assert (await api_client_unauth.post(f"{kit}/sheet/submit")).status_code == 200

    await _login(api_client_unauth, "rec@acme.com")

    reworded = await api_client_unauth.patch(
        kit, json={"questions": [{**Q1, "text": "Why us, really?"}, Q2]})
    assert reworded.status_code == 409
    assert "answered" in reworded.json()["detail"]

    # q2 was never answered, so its wording is still the recruiter's to fix.
    untouched = await api_client_unauth.patch(
        kit, json={"questions": [Q1, {**Q2, "text": "How, exactly?"}]})
    assert untouched.status_code == 200, untouched.text


@pytest.mark.asyncio
async def test_a_draft_answer_does_not_lock_the_wording(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    """Only SUBMITTED sheets lock wording. While an interviewer is still
    typing there is no record yet, and the recruiter may well be fixing the
    very question they are struggling to answer."""
    app_id = await _seed(db_session_with_schema)
    a = await _add(db_session_with_schema, "a@acme.com", Role.VIEWER)
    await _add(db_session_with_schema, "rec@acme.com", Role.RECRUITER)
    db_session_with_schema.add(InterviewAssignment(application_id=app_id, user_id=a.id))
    await db_session_with_schema.commit()
    kit = f"/api/applications/{app_id}/interview-kit"

    await _login(api_client_unauth, "a@acme.com")
    await api_client_unauth.patch(f"{kit}/sheet", json={
        "answers": {"q1": {"answer": "half a thought", "rating": None}},
        "verdict": {"decision": None, "note": None},
    })

    await _login(api_client_unauth, "rec@acme.com")
    r = await api_client_unauth.patch(
        kit, json={"questions": [{**Q1, "text": "Why us?"}, Q2]})

    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_assigned_interviewer_may_only_append(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_id = await _seed(db_session_with_schema)
    a = await _add(db_session_with_schema, "a@acme.com", Role.VIEWER)
    db_session_with_schema.add(InterviewAssignment(application_id=app_id, user_id=a.id))
    await db_session_with_schema.commit()
    kit = f"/api/applications/{app_id}/interview-kit"
    await _login(api_client_unauth, "a@acme.com")

    new_q = {"id": "mine", "text": "On-call?", "source": "probe"}
    r = await api_client_unauth.patch(kit, json={"questions": [Q1, Q2, new_q]})
    assert r.status_code == 200
    added = [q for q in r.json()["kit"]["questions"] if q["id"] == "mine"][0]
    assert added["added_by"] == a.id
    assert [q["added_by"] for q in r.json()["kit"]["questions"][:2]] == [None, None]

    r = await api_client_unauth.patch(kit, json={"questions": [Q2, Q1, new_q]})
    assert r.status_code == 403
    r = await api_client_unauth.patch(
        kit, json={"questions": [{**Q1, "text": "x"}, Q2, new_q]},
    )
    assert r.status_code == 403
    r = await api_client_unauth.patch(kit, json={"questions": [Q1, new_q]})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_unassigned_viewer_cannot_touch_questions(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_id = await _seed(db_session_with_schema)
    await _add(db_session_with_schema, "v@acme.com", Role.VIEWER)
    await _login(api_client_unauth, "v@acme.com")
    r = await api_client_unauth.patch(
        f"/api/applications/{app_id}/interview-kit",
        json={"questions": [Q1, Q2, {"id": "x", "text": "?", "source": "probe"}]},
    )
    assert r.status_code == 403
