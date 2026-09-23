"""Each track has its own panel (phase 3)."""
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from recruiter.api.candidates import get_engine_dep
from recruiter.auth.passwords import hash_password
from recruiter.main import app
from recruiter.models import InterviewAssignment, Role, User

PANEL = "/api/applications/{}/interviewers"


def _db():
    return async_sessionmaker(app.dependency_overrides[get_engine_dep](), expire_on_commit=False)


async def _user(email: str) -> int:
    async with _db()() as s:
        u = User(email=email, role=Role.VIEWER, is_active=True, password_hash=hash_password("x"))
        s.add(u)
        await s.commit()
        return u.id


async def _panel(app_id: int) -> list[tuple[int, str]]:
    async with _db()() as s:
        rows = (await s.execute(select(InterviewAssignment).where(
            InterviewAssignment.application_id == app_id,
        ).order_by(InterviewAssignment.id))).scalars().all()
        return [(r.user_id, r.track) for r in rows]


@pytest.mark.asyncio
async def test_the_panel_lists_each_interviewers_track(
    api_client: AsyncClient, seed_tracks,
) -> None:
    app_id, users = await seed_tracks()
    rows = (await api_client.get(PANEL.format(app_id))).json()
    assert {(r["user_id"], r["track"]) for r in rows} == {
        (users["tech@acme.com"], "tech"), (users["rh@acme.com"], "rh")}


@pytest.mark.asyncio
async def test_setting_one_tracks_panel_leaves_the_other_alone(
    api_client: AsyncClient, seed_tracks,
) -> None:
    app_id, users = await seed_tracks()
    carol = await _user("carol@acme.com")

    r = await api_client.put(f"{PANEL.format(app_id)}?track=rh",
                             json={"user_ids": [users["rh@acme.com"], carol]})

    assert r.status_code == 200, r.text
    assert sorted(await _panel(app_id)) == sorted([
        (users["tech@acme.com"], "tech"), (users["rh@acme.com"], "rh"), (carol, "rh")])


@pytest.mark.asyncio
async def test_a_person_cannot_join_a_second_track(api_client: AsyncClient, seed_tracks) -> None:
    app_id, users = await seed_tracks()
    r = await api_client.put(f"{PANEL.format(app_id)}?track=rh",
                             json={"user_ids": [users["tech@acme.com"]]})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_two_tracks_need_a_named_track(api_client: AsyncClient, seed_tracks) -> None:
    app_id, users = await seed_tracks()
    r = await api_client.put(PANEL.format(app_id), json={"user_ids": []})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_a_panel_picked_before_scheduling_goes_on_default(
    api_client: AsyncClient, create_scored_app,
) -> None:
    app_id = await create_scored_app()
    carol = await _user("carol@acme.com")
    r = await api_client.put(PANEL.format(app_id), json={"user_ids": [carol]})
    assert r.status_code == 200, r.text
    assert await _panel(app_id) == [(carol, "default")]


@pytest.mark.asyncio
async def test_removing_the_last_unsubmitted_sheet_closes_a_staffed_round(
    api_client: AsyncClient, seed_tracks,
) -> None:
    app_id, users = await seed_tracks(
        panel={"tech": ["tech@acme.com"], "rh": ["rh@acme.com", "rh2@acme.com"]},
        submitted=("tech@acme.com", "rh@acme.com"),
    )
    r = await api_client.put(f"{PANEL.format(app_id)}?track=rh",
                             json={"user_ids": [users["rh@acme.com"]]})
    assert r.status_code == 200, r.text
    stage = (await api_client.get(f"/api/applications/{app_id}")).json()["stage"]
    assert stage == "interviewed"


@pytest.mark.asyncio
async def test_emptying_a_track_does_not_close_the_round(
    api_client: AsyncClient, seed_tracks,
) -> None:
    app_id, _ = await seed_tracks(submitted=("tech@acme.com",))
    r = await api_client.put(f"{PANEL.format(app_id)}?track=rh", json={"user_ids": []})
    assert r.status_code == 200, r.text
    stage = (await api_client.get(f"/api/applications/{app_id}")).json()["stage"]
    assert stage == "scheduled", "an unstaffed track keeps the round open"
