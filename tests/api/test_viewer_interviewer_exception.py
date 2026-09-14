import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.auth.passwords import hash_password
from recruiter.models import Application, Candidate, InterviewAssignment, Job, Role, Stage, User

PW = "pw-12345678"
SHEET = {"answers": {}, "verdict": {"decision": "unsure", "note": None}}


@pytest.fixture(autouse=True)
def _reset_limiter():
    # This module logs users in and out; without a reset the shared 5/min
    # login budget (see rate_limit.py) trips across tests — and across
    # files, since the in-memory store is process-wide. Same pattern as
    # test_interview_sheets_api.py and test_viewer_matrix.py.
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
    app_row = Application(
        job_id=job.id, candidate_id=cand.id, stage=Stage.SCHEDULED, score=80,
        interview_kit={"status": "ready",
                       "questions": [{"id": "q1", "text": "Why?", "source": "probe"}]},
    )
    session.add(app_row)
    await session.commit()
    return app_row.id


@pytest.mark.asyncio
async def test_assigned_viewer_writes_only_their_own_sheet(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    assigned_app = await _seed(db_session_with_schema)
    other_app = await _seed(db_session_with_schema)
    v = await _add(db_session_with_schema, "v@acme.com", Role.VIEWER)
    db_session_with_schema.add(InterviewAssignment(application_id=assigned_app, user_id=v.id))
    await db_session_with_schema.commit()
    await _login(api_client_unauth, "v@acme.com")

    ok = await api_client_unauth.patch(
        f"/api/applications/{assigned_app}/interview-kit/sheet", json=SHEET)
    assert ok.status_code == 200

    # Not assigned there: the handler's row check, not the guard, says no.
    assert (await api_client_unauth.patch(
        f"/api/applications/{other_app}/interview-kit/sheet", json=SHEET)).status_code == 404

    # Everything else a viewer could not do before, they still cannot.
    assert (await api_client_unauth.patch(
        f"/api/applications/{assigned_app}", json={"stage": "interviewed"})).status_code == 403
    assert (await api_client_unauth.post(
        f"/api/applications/{assigned_app}/interview-kit/generate")).status_code == 403
    assert (await api_client_unauth.put(
        f"/api/applications/{assigned_app}/interviewers", json={"user_ids": []})).status_code == 403
