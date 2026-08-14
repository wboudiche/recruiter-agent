"""Admin-only user management, plus the guard rails that stop an admin
locking everyone out of the install."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.auth.passwords import hash_password, verify_password
from recruiter.auth.sessions import create_session, hash_token
from recruiter.models import AuthSession, Role, User


@pytest.fixture(autouse=True)
def _reset_limiter():
    # SlowAPI's in-memory storage persists across tests within a module;
    # without a reset, this module's own login attempts (several per test)
    # exhaust the 5/min budget on /login/password before later tests run,
    # and they'd 429 instead of exercising their actual assertions. Same
    # fix as test_password_login_users.py.
    from recruiter.api.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


async def _login(client: AsyncClient, email: str, password: str) -> None:
    r = await client.post(
        "/api/auth/login/password", json={"email": email, "password": password},
    )
    assert r.status_code == 204


async def _add(
    session: AsyncSession, email: str, role: Role, password: str = "pw",
    is_active: bool = True,
) -> User:
    user = User(
        email=email, role=role, is_active=is_active,
        password_hash=hash_password(password),
    )
    session.add(user)
    await session.commit()
    return user


@pytest.mark.asyncio
async def test_admin_can_create_and_list_users(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    await _add(db_session_with_schema, "boss@acme.com", Role.ADMIN, "s3cret")
    await _login(api_client_unauth, "boss@acme.com", "s3cret")

    created = await api_client_unauth.post("/api/users", json={
        "email": "new@acme.com", "name": "New", "role": "recruiter",
        "password": "initial-pw",
    })
    assert created.status_code == 201

    listed = (await api_client_unauth.get("/api/users")).json()
    assert {u["email"] for u in listed} == {"boss@acme.com", "new@acme.com"}
    # A user list must never carry hashes, even to an admin.
    assert all("password_hash" not in u for u in listed)


@pytest.mark.asyncio
async def test_non_admin_is_refused_every_user_route(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    await _add(db_session_with_schema, "rec@acme.com", Role.RECRUITER, "s3cret")
    await _login(api_client_unauth, "rec@acme.com", "s3cret")

    assert (await api_client_unauth.get("/api/users")).status_code == 403
    assert (await api_client_unauth.post("/api/users", json={
        "email": "x@acme.com", "role": "viewer", "password": "pw",
    })).status_code == 403


@pytest.mark.asyncio
async def test_non_admin_cannot_touch_credential_routes(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    """The sharp edge: PUT /api/settings lets a caller point local_llm_url
    at a server they control, and every CV then flows through it."""
    await _add(db_session_with_schema, "rec2@acme.com", Role.RECRUITER, "s3cret")
    await _login(api_client_unauth, "rec2@acme.com", "s3cret")

    assert (await api_client_unauth.put(
        "/api/settings", json={"local_llm_url": "https://evil.example"},
    )).status_code == 403
    assert (await api_client_unauth.post(
        "/api/sourcing/linkedin/disconnect",
    )).status_code == 403
    # Ordinary recruiting work is unaffected.
    assert (await api_client_unauth.get("/api/settings")).status_code == 200


@pytest.mark.asyncio
async def test_last_active_admin_cannot_be_demoted_or_deactivated(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    """One careless click would otherwise lock everyone out of user
    management permanently, recoverable only by editing the DB by hand."""
    boss = await _add(db_session_with_schema, "solo@acme.com", Role.ADMIN, "s3cret")
    await _add(db_session_with_schema, "rec3@acme.com", Role.RECRUITER)
    await _login(api_client_unauth, "solo@acme.com", "s3cret")

    demote = await api_client_unauth.patch(
        f"/api/users/{boss.id}", json={"role": "viewer"},
    )
    deactivate = await api_client_unauth.patch(
        f"/api/users/{boss.id}", json={"is_active": False},
    )

    assert demote.status_code == 409
    assert deactivate.status_code == 409


@pytest.mark.asyncio
async def test_admin_cannot_deactivate_themselves(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    boss = await _add(db_session_with_schema, "a1@acme.com", Role.ADMIN, "s3cret")
    await _add(db_session_with_schema, "a2@acme.com", Role.ADMIN)
    await _login(api_client_unauth, "a1@acme.com", "s3cret")

    r = await api_client_unauth.patch(
        f"/api/users/{boss.id}", json={"is_active": False},
    )

    assert r.status_code == 409
    # Pin the SELF-deactivation message specifically — there are two active
    # admins here, so the last-admin rule would also produce a 409, and a
    # bare status-code check can't tell which guard actually fired.
    assert r.json()["detail"] == "you cannot deactivate yourself"


@pytest.mark.asyncio
async def test_demoting_one_of_two_active_admins_succeeds(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    """The last-admin guard must not be so trigger-happy that it blocks a
    perfectly safe demotion — one admin remains active either way."""
    await _add(db_session_with_schema, "boss3@acme.com", Role.ADMIN, "s3cret")
    other = await _add(db_session_with_schema, "other-admin@acme.com", Role.ADMIN)
    await _login(api_client_unauth, "boss3@acme.com", "s3cret")

    r = await api_client_unauth.patch(
        f"/api/users/{other.id}", json={"role": "viewer"},
    )

    assert r.status_code == 200
    assert r.json()["role"] == "viewer"
    # Read back from a fresh session to prove the change was committed,
    # not just reflected in the in-memory response object.
    await db_session_with_schema.refresh(other)
    assert other.role == Role.VIEWER


@pytest.mark.asyncio
async def test_deactivating_a_non_last_admin_revokes_their_sessions(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    """If `_lock_active_admin_ids` ever spuriously saw zero admins left
    (e.g. an enum/column-type mismatch on `User.role == Role.ADMIN`), every
    admin deactivation would 409 and user management would be silently
    dead — with all the OTHER tests in this module still green. This test
    exists to catch exactly that: the allowed path must actually work."""
    await _add(db_session_with_schema, "boss4@acme.com", Role.ADMIN, "s3cret")
    other = await _add(db_session_with_schema, "other-admin2@acme.com", Role.ADMIN)
    await create_session(db_session_with_schema, user_id=other.id, ttl_days=7)
    await _login(api_client_unauth, "boss4@acme.com", "s3cret")

    r = await api_client_unauth.patch(
        f"/api/users/{other.id}", json={"is_active": False},
    )

    assert r.status_code == 200
    assert r.json()["is_active"] is False
    # Read from a fresh session (not the in-memory ORM object) to prove the
    # sessions were actually deleted and committed, not just queued.
    remaining = (await db_session_with_schema.execute(
        select(AuthSession).where(AuthSession.user_id == other.id)
    )).scalars().all()
    assert remaining == []


@pytest.mark.asyncio
async def test_password_reset_revokes_that_users_sessions(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    """A reset exists to cut off access. Leaving old cookies valid defeats
    the entire point of resetting."""
    victim = await _add(db_session_with_schema, "v@acme.com", Role.RECRUITER, "old-pw")
    await _login(api_client_unauth, "v@acme.com", "old-pw")
    assert (await api_client_unauth.get("/api/auth/me")).status_code == 200
    victim_cookie = api_client_unauth.cookies.get("recruiter_session")

    api_client_unauth.cookies.clear()
    await _add(db_session_with_schema, "boss2@acme.com", Role.ADMIN, "s3cret")
    await _login(api_client_unauth, "boss2@acme.com", "s3cret")
    reset = await api_client_unauth.post(
        f"/api/users/{victim.id}/password", json={"password": "brand-new"},
    )
    assert reset.status_code == 204

    api_client_unauth.cookies.clear()
    api_client_unauth.cookies.set("recruiter_session", victim_cookie)
    assert (await api_client_unauth.get("/api/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_users_change_their_own_password(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    """Without this, the admin who created the account knows the password
    forever."""
    user = await _add(db_session_with_schema, "self@acme.com", Role.VIEWER, "old-pw")
    await _login(api_client_unauth, "self@acme.com", "old-pw")

    wrong_current = await api_client_unauth.post("/api/auth/password", json={
        "current_password": "not-it", "new_password": "brand-new",
    })
    ok = await api_client_unauth.post("/api/auth/password", json={
        "current_password": "old-pw", "new_password": "brand-new",
    })

    assert wrong_current.status_code == 403
    assert ok.status_code == 204
    await db_session_with_schema.refresh(user)
    assert verify_password("brand-new", user.password_hash) is True


@pytest.mark.asyncio
async def test_self_service_password_change_revokes_other_sessions_but_keeps_current(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    """A self-service change made because you suspect compromise must kill
    the attacker's cookie — but must NOT log you out of the browser you
    just used to make the change, or people will avoid changing it at all."""
    user = await _add(db_session_with_schema, "multi@acme.com", Role.RECRUITER, "old-pw")
    other_token = await create_session(db_session_with_schema, user_id=user.id, ttl_days=7)
    await _login(api_client_unauth, "multi@acme.com", "old-pw")

    ok = await api_client_unauth.post("/api/auth/password", json={
        "current_password": "old-pw", "new_password": "brand-new",
    })
    assert ok.status_code == 204

    # The caller's own (just-used) session must still work.
    assert (await api_client_unauth.get("/api/auth/me")).status_code == 200
    # A second, pre-existing session for the same user must be dead. Uses a
    # SELECT (not Session.get()) so it actually round-trips to the DB rather
    # than answering from this session's identity-map cache of the row it
    # inserted above — `.get()` would return that stale, unexpired object
    # without ever checking whether the API's own session deleted it.
    other_row = (await db_session_with_schema.execute(
        select(AuthSession).where(AuthSession.id == hash_token(other_token))
    )).scalar_one_or_none()
    assert other_row is None
