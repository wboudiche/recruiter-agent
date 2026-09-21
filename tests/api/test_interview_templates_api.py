import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.auth.passwords import hash_password
from recruiter.models import Role, User

BASE = "/api/interview-templates"
Q = [{"id": "q1", "text": "Why this company?"}]


@pytest.mark.asyncio
async def test_create_then_list(api_client: AsyncClient) -> None:
    r = await api_client.post(BASE, json={
        "name": "RH screen", "questions": Q, "probe_mode": "none",
        "include_job_questions": False,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["probe_mode"], body["include_job_questions"], body["is_active"]) == (
        "none", False, True)

    listed = (await api_client.get(BASE)).json()
    assert [t["name"] for t in listed] == ["RH screen"]


@pytest.mark.asyncio
async def test_a_new_template_defaults_to_technical_behaviour(api_client: AsyncClient) -> None:
    body = (await api_client.post(BASE, json={"name": "Technical"})).json()
    assert (body["probe_mode"], body["include_job_questions"]) == ("score_gaps", True)


@pytest.mark.asyncio
async def test_duplicate_question_ids_are_refused(api_client: AsyncClient) -> None:
    r = await api_client.post(BASE, json={"name": "T", "questions": [
        {"id": "q1", "text": "a"}, {"id": "q1", "text": "b"}]})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_question_ids_longer_than_48_are_refused(api_client: AsyncClient) -> None:
    """A snapshotted id is t<template_id>-<id>, and kit ids are capped at 64."""
    r = await api_client.post(BASE, json={"name": "T", "questions": [
        {"id": "x" * 49, "text": "a"}]})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_names_are_unique_among_active_templates_only(api_client: AsyncClient) -> None:
    first = (await api_client.post(BASE, json={"name": "RH screen"})).json()
    clash = await api_client.post(BASE, json={"name": "RH screen"})
    assert clash.status_code == 409

    await api_client.patch(f"{BASE}/{first['id']}", json={"is_active": False})
    again = await api_client.post(BASE, json={"name": "RH screen"})
    assert again.status_code == 201, "archiving should free the name"


@pytest.mark.asyncio
async def test_archived_templates_are_hidden_unless_asked_for(api_client: AsyncClient) -> None:
    tpl = (await api_client.post(BASE, json={"name": "Old"})).json()
    await api_client.patch(f"{BASE}/{tpl['id']}", json={"is_active": False})

    assert (await api_client.get(BASE)).json() == []
    archived = await api_client.get(f"{BASE}?include_archived=true")
    assert [t["name"] for t in archived.json()] == ["Old"]


@pytest.mark.asyncio
async def test_patch_clears_description_but_refuses_nulling_a_required_field(
    api_client: AsyncClient,
) -> None:
    tpl = (await api_client.post(BASE, json={"name": "T", "description": "x"})).json()
    cleared = await api_client.patch(f"{BASE}/{tpl['id']}", json={"description": None})
    assert cleared.json()["description"] is None
    assert (await api_client.patch(f"{BASE}/{tpl['id']}", json={"name": None})).status_code == 422


@pytest.mark.asyncio
async def test_a_job_can_point_at_a_default_template(
    api_client: AsyncClient, create_scored_app,
) -> None:
    await create_scored_app()
    job = (await api_client.get("/api/jobs")).json()[0]
    tpl = (await api_client.post(BASE, json={"name": "Technical"})).json()

    set_ = await api_client.patch(f"/api/jobs/{job['id']}",
                                  json={"default_interview_template_id": tpl["id"]})
    assert set_.json()["default_interview_template_id"] == tpl["id"]

    # Absent leaves it alone; explicit null clears it.
    kept = await api_client.patch(f"/api/jobs/{job['id']}", json={"title": "Renamed"})
    assert kept.json()["default_interview_template_id"] == tpl["id"]
    cleared = await api_client.patch(f"/api/jobs/{job['id']}",
                                     json={"default_interview_template_id": None})
    assert cleared.json()["default_interview_template_id"] is None


@pytest.mark.asyncio
async def test_an_archived_template_cannot_become_a_job_default(
    api_client: AsyncClient, create_scored_app,
) -> None:
    await create_scored_app()
    job = (await api_client.get("/api/jobs")).json()[0]
    tpl = (await api_client.post(BASE, json={"name": "Old"})).json()
    await api_client.patch(f"{BASE}/{tpl['id']}", json={"is_active": False})

    r = await api_client.patch(f"/api/jobs/{job['id']}",
                               json={"default_interview_template_id": tpl["id"]})
    assert r.status_code == 422


PW = "pw-12345678"


@pytest.fixture(autouse=True)
def _reset_limiter():
    # Several logins per test; without a reset the shared 5/min login
    # budget trips across tests and files (see rate_limit.py).
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


@pytest.mark.asyncio
async def test_recruiters_manage_templates_and_viewers_cannot(
    api_client_unauth: AsyncClient, db_session_with_schema,
) -> None:
    await _add(db_session_with_schema, "rec@acme.com", Role.RECRUITER)
    await _add(db_session_with_schema, "view@acme.com", Role.VIEWER)

    await _login(api_client_unauth, "rec@acme.com")
    assert (await api_client_unauth.post(BASE, json={"name": "T"})).status_code == 201

    await _login(api_client_unauth, "view@acme.com")
    assert (await api_client_unauth.post(BASE, json={"name": "U"})).status_code == 403
