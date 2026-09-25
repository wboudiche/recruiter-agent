"""Reading, and closing, a round with two tracks (phase 3)."""
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from recruiter.api.candidates import get_engine_dep
from recruiter.auth.passwords import hash_password
from recruiter.main import app
from recruiter.models import InterviewAssignment, InterviewKitRow, Role, User

KIT = "/api/applications/{}/interview-kit"


@pytest.fixture(autouse=True)
def _reset_limiter():
    # Several logins per test; without a reset the shared 5/min login
    # budget trips across tests and files (see rate_limit.py).
    from recruiter.api.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


async def _kits(app_id: int) -> list[InterviewKitRow]:
    SessionLocal = async_sessionmaker(app.dependency_overrides[get_engine_dep](),
                                      expire_on_commit=False)
    async with SessionLocal() as s:
        return list((await s.execute(
            select(InterviewKitRow).where(InterviewKitRow.application_id == app_id)
            .order_by(InterviewKitRow.id))).scalars().all())


@pytest.mark.asyncio
async def test_a_recruiter_sees_every_track_in_creation_order(
    api_client: AsyncClient, seed_tracks,
) -> None:
    app_id, _ = await seed_tracks()
    body = (await api_client.get(KIT.format(app_id))).json()

    assert [t["track"] for t in body["tracks"]] == ["tech", "rh"]
    assert [q["id"] for q in body["tracks"][1]["kit"]["questions"]] == ["r1"]
    assert body["kit"]["questions"][0]["id"] == "q1", "compat kit: the round's first track"
    assert sorted(s["track"] for s in body["sheets"]) == ["rh", "tech"]


@pytest.mark.asyncio
async def test_an_interviewer_sees_only_their_own_track(
    api_client_unauth: AsyncClient, seed_tracks, login_as,
) -> None:
    app_id, _ = await seed_tracks(
        panel={"tech": ["tech@acme.com"], "rh": ["rh@acme.com", "rh2@acme.com"]},
        submitted=("tech@acme.com", "rh@acme.com", "rh2@acme.com"),
    )
    await login_as(api_client_unauth, "rh@acme.com")
    body = (await api_client_unauth.get(KIT.format(app_id))).json()

    assert [t["track"] for t in body["tracks"]] == ["rh"]
    assert body["kit"]["questions"][0]["id"] == "r1", "compat kit: the caller's own track"
    assert sorted(s["email"] for s in body["sheets"]) == ["rh2@acme.com", "rh@acme.com"], (
        "after submitting, the RH panel's sheets — never the technical one")


@pytest.mark.asyncio
async def test_the_round_waits_for_an_unstaffed_track(
    api_client_unauth: AsyncClient, seed_tracks, login_as,
) -> None:
    app_id, _ = await seed_tracks(panel={"tech": ["tech@acme.com"]})
    await login_as(api_client_unauth, "tech@acme.com")
    r = await api_client_unauth.post(f"{KIT.format(app_id)}/sheet/submit")
    assert r.status_code == 200, r.text
    stage = (await api_client_unauth.get(f"/api/applications/{app_id}")).json()["stage"]
    assert stage == "scheduled", "the RH track has nobody on it yet"

    SessionLocal = async_sessionmaker(app.dependency_overrides[get_engine_dep](),
                                      expire_on_commit=False)
    async with SessionLocal() as s:
        # Same password as seed_tracks' interviewers, so login_as works.
        carol = User(email="carol@acme.com", role=Role.VIEWER, is_active=True,
                     password_hash=hash_password("pw-12345678"))
        s.add(carol)
        await s.flush()
        s.add(InterviewAssignment(application_id=app_id, user_id=carol.id, round=1, track="rh"))
        await s.commit()

    await login_as(api_client_unauth, "carol@acme.com")
    assert (await api_client_unauth.post(f"{KIT.format(app_id)}/sheet/submit")).status_code == 200
    stage = (await api_client_unauth.get(f"/api/applications/{app_id}")).json()["stage"]
    assert stage == "interviewed"
    assert all(k.closed_at for k in await _kits(app_id)), "closing stamps every track"


@pytest.mark.asyncio
async def test_marking_interviewed_by_hand_closes_every_track(
    api_client: AsyncClient, seed_tracks,
) -> None:
    app_id, _ = await seed_tracks()
    r = await api_client.patch(f"/api/applications/{app_id}", json={"stage": "interviewed"})
    assert r.status_code == 200, r.text
    assert all(k.closed_at for k in await _kits(app_id))


@pytest.mark.asyncio
async def test_a_track_says_what_kind_of_interview_it_is(
    api_client: AsyncClient, seed_tracks,
) -> None:
    """The kit screen labels each track, and an interviewer cannot read the
    templates list — so the settings the label is derived from travel with
    the kit, out of the snapshot it was built from."""
    app_id, _ = await seed_tracks()
    SessionLocal = async_sessionmaker(app.dependency_overrides[get_engine_dep](),
                                      expire_on_commit=False)
    async with SessionLocal() as s:
        kit = (await s.execute(select(InterviewKitRow).where(
            InterviewKitRow.application_id == app_id, InterviewKitRow.track == "rh",
        ))).scalar_one()
        kit.template_name = "RH screen"
        kit.template_snapshot = {
            "questions": [], "probe_mode": "profile", "include_job_questions": False,
        }
        await s.commit()

    tracks = (await api_client.get(KIT.format(app_id))).json()["tracks"]
    by_track = {t["track"]: t for t in tracks}

    assert by_track["rh"]["probe_mode"] == "profile"
    assert by_track["rh"]["include_job_questions"] is False
    assert by_track["tech"]["probe_mode"] is None, "a kit with no template has no settings"
