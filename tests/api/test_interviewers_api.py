from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recruiter.api.candidates import get_engine_dep
from recruiter.auth.passwords import hash_password
from recruiter.main import app
from recruiter.models import Application, Candidate, InterviewAssignment, Job, Role, Stage, User


@pytest.fixture(autouse=True)
def _reset_limiter():
    # This module logs users in and out; without a reset the shared 5/min
    # login budget (see rate_limit.py) trips across tests — and across
    # files, since the in-memory store is process-wide. Same pattern as
    # test_interview_sheets_api.py and test_viewer_interviewer_exception.py.
    from recruiter.api.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


async def _add(session: AsyncSession, email: str, role: Role, active: bool = True) -> User:
    user = User(email=email, role=role, is_active=active,
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
    app_row = Application(job_id=job.id, candidate_id=candidate.id, stage=Stage.SCHEDULED)
    session.add(app_row)
    await session.commit()
    return app_row.id


def _sessionmaker():
    return async_sessionmaker(app.dependency_overrides[get_engine_dep](), expire_on_commit=False)


async def _add_user_via_engine(email: str, role: Role, active: bool = True) -> int:
    async with _sessionmaker()() as session:
        return (await _add(session, email, role, active)).id


@pytest.mark.asyncio
async def test_put_creates_then_removes_assignments(
    api_client: AsyncClient, create_scored_app,
) -> None:
    app_id = await create_scored_app()
    a = await _add_user_via_engine("a@acme.com", Role.VIEWER)
    b = await _add_user_via_engine("b@acme.com", Role.RECRUITER)

    put = await api_client.put(
        f"/api/applications/{app_id}/interviewers", json={"user_ids": [a, b]},
    )
    assert put.status_code == 200
    assert [r["user_id"] for r in put.json()] == [a, b]
    assert put.json()[0]["email"] == "a@acme.com"
    assert put.json()[0]["submitted_at"] is None

    put = await api_client.put(f"/api/applications/{app_id}/interviewers", json={"user_ids": [b]})
    assert [r["user_id"] for r in put.json()] == [b]

    get = await api_client.get(f"/api/applications/{app_id}/interviewers")
    assert [r["user_id"] for r in get.json()] == [b]


@pytest.mark.asyncio
async def test_put_is_idempotent(api_client: AsyncClient, create_scored_app) -> None:
    app_id = await create_scored_app()
    a = await _add_user_via_engine("a@acme.com", Role.VIEWER)
    for _ in range(2):
        r = await api_client.put(
            f"/api/applications/{app_id}/interviewers", json={"user_ids": [a]},
        )
        assert r.status_code == 200
    listed = await api_client.get(f"/api/applications/{app_id}/interviewers")
    assert len(listed.json()) == 1


@pytest.mark.asyncio
async def test_put_refuses_removing_a_submitted_sheet(
    api_client: AsyncClient, create_scored_app,
) -> None:
    from datetime import UTC, datetime
    app_id = await create_scored_app()
    a = await _add_user_via_engine("a@acme.com", Role.VIEWER)
    async with _sessionmaker()() as session:
        session.add(InterviewAssignment(application_id=app_id, user_id=a,
                                        submitted_at=datetime.now(UTC)))
        await session.commit()
    r = await api_client.put(f"/api/applications/{app_id}/interviewers", json={"user_ids": []})
    assert r.status_code == 409
    assert "submitted" in r.json()["detail"]


@pytest.mark.asyncio
async def test_put_rejects_unknown_and_inactive_users(
    api_client: AsyncClient, create_scored_app,
) -> None:
    app_id = await create_scored_app()
    inactive = await _add_user_via_engine("gone@acme.com", Role.VIEWER, active=False)
    r = await api_client.put(
        f"/api/applications/{app_id}/interviewers", json={"user_ids": [999999]},
    )
    assert r.status_code == 422
    r = await api_client.put(
        f"/api/applications/{app_id}/interviewers", json={"user_ids": [inactive]},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_put_404s_for_unknown_application(api_client: AsyncClient) -> None:
    r = await api_client.put("/api/applications/999999/interviewers", json={"user_ids": []})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_viewer_can_list_but_not_assign(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_id = await _seed_application(db_session_with_schema)
    await _add(db_session_with_schema, "viewer@acme.com", Role.VIEWER)
    await _login(api_client_unauth, "viewer@acme.com")
    listed = await api_client_unauth.get(f"/api/applications/{app_id}/interviewers")
    assert listed.status_code == 200
    r = await api_client_unauth.put(
        f"/api/applications/{app_id}/interviewers", json={"user_ids": []},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_directory_lists_active_users_for_recruiters_only(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    await _add(db_session_with_schema, "rec@acme.com", Role.RECRUITER)
    await _add(db_session_with_schema, "viewer@acme.com", Role.VIEWER)
    await _add(db_session_with_schema, "gone@acme.com", Role.VIEWER, active=False)

    await _login(api_client_unauth, "rec@acme.com")
    r = await api_client_unauth.get("/api/users/directory")
    assert r.status_code == 200
    emails = [u["email"] for u in r.json()]
    assert "gone@acme.com" not in emails
    assert {"rec@acme.com", "viewer@acme.com"} <= set(emails)
    assert set(r.json()[0]) == {"id", "name", "email", "role"}

    await api_client_unauth.post("/api/auth/logout")
    await _login(api_client_unauth, "viewer@acme.com")
    assert (await api_client_unauth.get("/api/users/directory")).status_code == 403


@pytest.mark.asyncio
async def test_put_closes_the_round_when_the_last_unsubmitted_interviewer_is_removed(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """A and B are on the panel; A has already submitted. Removing B — the
    only one left who hasn't — leaves every remaining assignment submitted,
    so the round must close exactly as a late submit would."""
    app_id = await create_scored_app()
    a = await _add_user_via_engine("a@acme.com", Role.VIEWER)
    b = await _add_user_via_engine("b@acme.com", Role.VIEWER)
    async with _sessionmaker()() as session:
        await session.execute(
            update(Application).where(Application.id == app_id).values(
                stage=Stage.SCHEDULED,
                interview_kit={"status": "ready",
                               "questions": [{"id": "q1", "text": "Why?", "source": "probe"}]},
            )
        )
        session.add(InterviewAssignment(application_id=app_id, user_id=a,
                                        submitted_at=datetime.now(UTC)))
        session.add(InterviewAssignment(application_id=app_id, user_id=b))
        await session.commit()

    resp = await api_client.put(
        f"/api/applications/{app_id}/interviewers", json={"user_ids": [a]},
    )
    assert resp.status_code == 200

    app_read = (await api_client.get(f"/api/applications/{app_id}")).json()
    assert app_read["stage"] == "interviewed"


@pytest.mark.asyncio
async def test_put_keeps_an_already_assigned_user_even_if_deactivated_since(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """A user assigned while active, then deactivated, must not make the
    panel unsaveable: only ids being newly ADDED are checked for is_active."""
    app_id = await create_scored_app()
    x = await _add_user_via_engine("x@acme.com", Role.VIEWER)
    y = await _add_user_via_engine("y@acme.com", Role.VIEWER)
    put = await api_client.put(
        f"/api/applications/{app_id}/interviewers", json={"user_ids": [x]},
    )
    assert put.status_code == 200

    async with _sessionmaker()() as session:
        await session.execute(update(User).where(User.id == x).values(is_active=False))
        await session.commit()

    resp = await api_client.put(
        f"/api/applications/{app_id}/interviewers", json={"user_ids": [x, y]},
    )
    assert resp.status_code == 200
    assert {r["user_id"] for r in resp.json()} == {x, y}


@pytest.mark.asyncio
async def test_put_refuses_removing_an_unsubmitted_sheet_with_content(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """An unsubmitted draft with an answer must not vanish silently by
    unticking a name — same principle as the submitted-sheet 409, one step
    earlier."""
    app_id = await create_scored_app()
    a = await _add_user_via_engine("a@acme.com", Role.VIEWER)
    async with _sessionmaker()() as session:
        session.add(InterviewAssignment(
            application_id=app_id, user_id=a,
            sheet={"answers": {"q1": {"answer": "Some notes.", "rating": None}},
                   "verdict": {"decision": None, "note": None}},
        ))
        await session.commit()
    r = await api_client.put(f"/api/applications/{app_id}/interviewers", json={"user_ids": []})
    assert r.status_code == 409
    assert "content" in r.json()["detail"]


@pytest.mark.asyncio
async def test_put_no_change_save_does_not_close_the_round(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """R1: a candidate re-entered into SCHEDULED for a second round can
    still have round-1 assignment rows whose submitted_at is set (frozen
    but not itself grounds for closing anything). Saving the Assign dialog
    with the exact same panel must not run close_round_if_complete at all —
    only removing a row should ever be able to close the round."""
    app_id = await create_scored_app()
    a = await _add_user_via_engine("a@acme.com", Role.VIEWER)
    async with _sessionmaker()() as session:
        await session.execute(
            update(Application).where(Application.id == app_id).values(
                stage=Stage.SCHEDULED,
                interview_kit={"status": "ready",
                               "questions": [{"id": "q1", "text": "Why?", "source": "probe"}]},
            )
        )
        session.add(InterviewAssignment(application_id=app_id, user_id=a,
                                        submitted_at=datetime.now(UTC)))
        await session.commit()

    resp = await api_client.put(
        f"/api/applications/{app_id}/interviewers", json={"user_ids": [a]},
    )
    assert resp.status_code == 200

    app_read = (await api_client.get(f"/api/applications/{app_id}")).json()
    assert app_read["stage"] == "scheduled"


@pytest.mark.asyncio
async def test_put_removes_an_inactive_assignees_populated_draft(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """R8: sheet_has_content only blocks removal of an ACTIVE assignee.
    Once X is deactivated their populated-but-unsubmitted draft must not
    strand the panel — there is no way for X to come back and submit or
    clear it themselves."""
    app_id = await create_scored_app()
    x = await _add_user_via_engine("x@acme.com", Role.VIEWER)
    async with _sessionmaker()() as session:
        session.add(InterviewAssignment(
            application_id=app_id, user_id=x,
            sheet={"answers": {"q1": {"answer": "Some notes.", "rating": None}},
                   "verdict": {"decision": None, "note": None}},
        ))
        await session.execute(update(User).where(User.id == x).values(is_active=False))
        await session.commit()

    r = await api_client.put(f"/api/applications/{app_id}/interviewers", json={"user_ids": []})
    assert r.status_code == 200
    assert r.json() == []
