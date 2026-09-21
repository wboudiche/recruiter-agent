import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recruiter.api.candidates import get_engine_dep
from recruiter.auth.passwords import hash_password
from recruiter.main import app
from recruiter.models import Application, Candidate, InterviewAssignment, Job, Role, Stage, User
from recruiter.models.interview_kit_row import InterviewKitRow

PW = "pw-12345678"


@pytest.fixture(autouse=True)
def _reset_limiter():
    # This module logs many different users in and out per test; without a
    # reset the shared 5/min login budget (see rate_limit.py) trips across
    # tests — and across files, since the in-memory store is process-wide.
    # Same pattern as test_viewer_matrix.py and test_user_admin_audit.py.
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


async def _seed_scheduled_with_kit(session: AsyncSession) -> int:
    job = Job(title="Backend", description="x", criteria=[])
    session.add(job)
    await session.flush()
    cand = Candidate(source_type="paste", full_name="Marie", email="m@example.com")
    session.add(cand)
    await session.flush()
    app_row = Application(
        job_id=job.id, candidate_id=cand.id, stage=Stage.SCHEDULED, score=80,
    )
    session.add(app_row)
    await session.flush()
    session.add(InterviewKitRow(
        application_id=app_row.id, round=1, track="default",
        status="ready", generated_at="2026-09-14T00:00:00+00:00",
        questions=[{"id": "q1", "text": "Why?", "source": "probe"},
                   {"id": "q2", "text": "How?", "source": "probe"}],
    ))
    await session.commit()
    return app_row.id


async def _assign(session: AsyncSession, app_id: int, *user_ids: int) -> None:
    for uid in user_ids:
        session.add(InterviewAssignment(application_id=app_id, user_id=uid))
    await session.commit()


SHEET = {"answers": {"q1": {"answer": "Two years on EKS.", "rating": "strong"}},
         "verdict": {"decision": "hire", "note": "Strong."}}


@pytest.mark.asyncio
async def test_assigned_interviewer_saves_and_reads_back_own_sheet(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_id = await _seed_scheduled_with_kit(db_session_with_schema)
    a = await _add(db_session_with_schema, "a@acme.com", Role.VIEWER)
    await _assign(db_session_with_schema, app_id, a.id)
    await _login(api_client_unauth, "a@acme.com")

    r = await api_client_unauth.patch(f"/api/applications/{app_id}/interview-kit/sheet", json=SHEET)
    assert r.status_code == 200
    sheets = r.json()["sheets"]
    assert len(sheets) == 1
    assert sheets[0]["user_id"] == a.id
    assert sheets[0]["sheet"]["answers"]["q1"]["rating"] == "strong"
    assert sheets[0]["sheet"]["verdict"]["decision"] == "hire"
    assert sheets[0]["submitted_at"] is None


@pytest.mark.asyncio
async def test_unassigned_caller_gets_404_on_sheet_routes(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_id = await _seed_scheduled_with_kit(db_session_with_schema)
    await _add(db_session_with_schema, "v@acme.com", Role.VIEWER)
    await _login(api_client_unauth, "v@acme.com")
    assert (await api_client_unauth.patch(
        f"/api/applications/{app_id}/interview-kit/sheet", json=SHEET)).status_code == 404
    assert (await api_client_unauth.post(
        f"/api/applications/{app_id}/interview-kit/sheet/submit")).status_code == 404


@pytest.mark.asyncio
async def test_second_submit_is_409(api_client: AsyncClient, create_scored_app) -> None:
    app_id = await create_scored_app()
    engine = app.dependency_overrides[get_engine_dep]()
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        s.add(InterviewKitRow(
            application_id=app_id, round=1, track="default", status="ready",
            questions=[{"id": "q1", "text": "Why?", "source": "probe"}],
        ))
        await s.commit()
    sheet_url = f"/api/applications/{app_id}/interview-kit/sheet"
    assert (await api_client.post(f"{sheet_url}/submit")).status_code == 200
    assert (await api_client.post(f"{sheet_url}/submit")).status_code == 409
    assert (await api_client.patch(sheet_url, json=SHEET)).status_code == 409


@pytest.mark.asyncio
async def test_recruiter_with_no_assignments_gets_a_sheet_on_first_save(
    api_client: AsyncClient, create_scored_app,
) -> None:
    app_id = await create_scored_app()
    engine = app.dependency_overrides[get_engine_dep]()
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        s.add(InterviewKitRow(
            application_id=app_id, round=1, track="default", status="ready",
            questions=[{"id": "q1", "text": "Why?", "source": "probe"}],
        ))
        await s.commit()
    r = await api_client.patch(f"/api/applications/{app_id}/interview-kit/sheet", json=SHEET)
    assert r.status_code == 200
    assert len(r.json()["sheets"]) == 1
    interviewers = await api_client.get(f"/api/applications/{app_id}/interviewers")
    assert len(interviewers.json()) == 1


@pytest.mark.asyncio
async def test_answers_for_unknown_questions_are_dropped_on_save(
    api_client: AsyncClient, create_scored_app,
) -> None:
    app_id = await create_scored_app()
    engine = app.dependency_overrides[get_engine_dep]()
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        s.add(InterviewKitRow(
            application_id=app_id, round=1, track="default", status="ready",
            questions=[{"id": "q1", "text": "Why?", "source": "probe"}],
        ))
        await s.commit()
    body = {
        "answers": {"q1": {"answer": "a", "rating": None}, "zzz": {"answer": "b", "rating": None}},
        "verdict": {"decision": None, "note": None},
    }
    r = await api_client.patch(f"/api/applications/{app_id}/interview-kit/sheet", json=body)
    assert set(r.json()["sheets"][0]["sheet"]["answers"]) == {"q1"}


@pytest.mark.asyncio
async def test_visibility_blind_until_submitted(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_id = await _seed_scheduled_with_kit(db_session_with_schema)
    a = await _add(db_session_with_schema, "a@acme.com", Role.VIEWER)
    b = await _add(db_session_with_schema, "b@acme.com", Role.VIEWER)
    rec = await _add(db_session_with_schema, "rec@acme.com", Role.RECRUITER)
    await _add(db_session_with_schema, "other@acme.com", Role.VIEWER)
    await _assign(db_session_with_schema, app_id, a.id, b.id)
    kit = f"/api/applications/{app_id}/interview-kit"

    await _login(api_client_unauth, "b@acme.com")
    await api_client_unauth.post(f"{kit}/sheet/submit")

    await _login(api_client_unauth, "a@acme.com")
    seen = (await api_client_unauth.get(kit)).json()["sheets"]
    assert [s["user_id"] for s in seen] == [a.id]
    await api_client_unauth.post(f"{kit}/sheet/submit")
    seen = (await api_client_unauth.get(kit)).json()["sheets"]
    assert {s["user_id"] for s in seen} == {a.id, b.id}

    await _login(api_client_unauth, "rec@acme.com")
    seen = (await api_client_unauth.get(kit)).json()["sheets"]
    assert len(seen) == 2

    await _login(api_client_unauth, "other@acme.com")
    assert (await api_client_unauth.get(kit)).json()["sheets"] == []
    assert rec.id  # silence unused warning


@pytest.mark.asyncio
async def test_stage_moves_only_when_every_sheet_is_in(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_id = await _seed_scheduled_with_kit(db_session_with_schema)
    a = await _add(db_session_with_schema, "a@acme.com", Role.VIEWER)
    b = await _add(db_session_with_schema, "b@acme.com", Role.VIEWER)
    await _assign(db_session_with_schema, app_id, a.id, b.id)
    kit = f"/api/applications/{app_id}/interview-kit"

    await _login(api_client_unauth, "a@acme.com")
    assert (await api_client_unauth.post(f"{kit}/sheet/submit")).status_code == 200
    app_json = (await api_client_unauth.get(f"/api/applications/{app_id}")).json()
    assert app_json["stage"] == "scheduled"

    await _login(api_client_unauth, "b@acme.com")
    r = await api_client_unauth.post(f"{kit}/sheet/submit")
    assert r.json()["kit"]["closed_at"] is not None
    app_json = (await api_client_unauth.get(f"/api/applications/{app_id}")).json()
    assert app_json["stage"] == "interviewed"
    assert app_json["interviewed_at"] is not None


@pytest.mark.asyncio
async def test_manual_move_sets_closed_at_and_late_submit_does_not_move_again(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_id = await _seed_scheduled_with_kit(db_session_with_schema)
    a = await _add(db_session_with_schema, "a@acme.com", Role.VIEWER)
    await _add(db_session_with_schema, "rec@acme.com", Role.RECRUITER)
    await _assign(db_session_with_schema, app_id, a.id)
    kit = f"/api/applications/{app_id}/interview-kit"

    await _login(api_client_unauth, "rec@acme.com")
    r = await api_client_unauth.patch(f"/api/applications/{app_id}", json={"stage": "interviewed"})
    assert r.status_code == 200
    assert (await api_client_unauth.get(kit)).json()["kit"]["closed_at"] is not None
    # Recruiter moves it on to OFFER; the late sheet must not drag it back or forward.
    await api_client_unauth.patch(f"/api/applications/{app_id}", json={"stage": "offer"})

    await _login(api_client_unauth, "a@acme.com")
    assert (await api_client_unauth.patch(f"{kit}/sheet", json=SHEET)).status_code == 200
    assert (await api_client_unauth.post(f"{kit}/sheet/submit")).status_code == 200
    assert (await api_client_unauth.get(f"/api/applications/{app_id}")).json()["stage"] == "offer"


@pytest.mark.asyncio
async def test_sheet_routes_404_without_a_kit(api_client: AsyncClient, create_scored_app) -> None:
    app_id = await create_scored_app()
    resp = await api_client.patch(f"/api/applications/{app_id}/interview-kit/sheet", json=SHEET)
    assert resp.status_code == 404
