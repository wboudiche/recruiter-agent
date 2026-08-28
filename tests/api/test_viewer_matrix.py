"""A viewer must be read-only, and must STAY read-only as routes are added.

Enforcement is default-deny: any mutating method is refused unless the
route template is explicitly allowlisted. The fail-closed test below is
the property the whole design exists for — if it is ever deleted as
"weird", a future route silently ships open to viewers.
"""

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.deps import viewer_readonly_guard
from recruiter.api.permissions import MUTATING_METHODS, VIEWER_ALLOWED_ROUTES
from recruiter.auth.passwords import hash_password
from recruiter.config import get_config
from recruiter.main import app
from recruiter.models import Role, User


@pytest.fixture(autouse=True)
def _reset_limiter():
    from recruiter.api.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()
    get_config.cache_clear()


async def _add(session: AsyncSession, email: str, role: Role) -> User:
    user = User(
        email=email, role=role, is_active=True,
        password_hash=hash_password("pw-12345678"),
    )
    session.add(user)
    await session.commit()
    return user


async def _login(client: AsyncClient, email: str) -> None:
    r = await client.post(
        "/api/auth/login/password",
        json={"email": email, "password": "pw-12345678"},
    )
    assert r.status_code == 204


def _mutating_routes() -> list[tuple[str, str]]:
    """Every mutating route the app actually exposes, minus the allowlist.

    Introspected rather than hardcoded so a new route joins this test
    automatically instead of being forgotten.
    """
    found: list[tuple[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if not path or not path.startswith("/api/"):
            continue
        for method in methods & MUTATING_METHODS:
            if (method, path) in VIEWER_ALLOWED_ROUTES:
                continue
            found.append((method, path))
    return sorted(found)


def test_the_route_inventory_is_not_empty() -> None:
    """Guards the guard: if introspection silently returned nothing, the
    parametrised test below would vacuously pass for every route."""
    assert len(_mutating_routes()) >= 15


def test_every_api_route_carries_the_viewer_guard() -> None:
    """Checks the WIRING, not just the observed behaviour.

    main.py mounts every /api router through an intermediate
    `_api_router = APIRouter(dependencies=[Depends(viewer_readonly_guard)])`
    rather than putting the dependency on `app` directly, because the
    latter also gates /health and forces it to touch the database (see
    task-1-report.md). That indirection only holds the default-deny
    promise if every /api router is actually mounted on `_api_router`.
    A router mounted on `app` directly would still show up in
    `_mutating_routes()` above (which walks `app.routes` regardless of
    wiring) and get caught by the parametrised behavioural test — but
    catching it here, by inspecting the dependency graph FastAPI actually
    built, points straight at the fix instead of leaving someone to
    guess why a route is unexpectedly reachable.
    """
    missing = []
    for route in app.routes:
        path = getattr(route, "path", None)
        if not path or not path.startswith("/api"):
            continue
        guard_calls = [dep.dependency for dep in getattr(route, "dependencies", []) or []]
        if viewer_readonly_guard not in guard_calls:
            missing.append(path)
    assert missing == [], (
        "these /api routes do not carry viewer_readonly_guard in "
        f"route.dependencies: {missing}. Mount the router that owns them "
        "on `_api_router` in main.py (via `_api_router.include_router(...)`), "
        "not on `app` directly."
    )


def test_no_mutating_route_exists_outside_api() -> None:
    """The guard is wired onto /api routers only (see the test above), so
    a mutating route mounted OUTSIDE /api — e.g. `/admin/purge` or
    `/webhooks/stripe` — would be both unguarded and invisible to
    `_mutating_routes()`, which filters on `path.startswith("/api/")`.
    Under the app-level wiring this task's brief originally specified,
    such a route WOULD have been covered; the /health fix (see
    task-1-report.md) narrowed the guard's reach to /api on purpose, and
    this test is what keeps that narrowing from becoming a silent gap.

    If this fails, you added a mutating route outside /api. Either mount
    it under /api on `_api_router` (main.py) so the existing guard covers
    it, or, if it genuinely must live outside /api, extend
    viewer_readonly_guard's wiring to cover it explicitly and update this
    test's exemption alongside that change — do not just delete this
    assertion.
    """
    offenders = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if not path or path.startswith("/api"):
            continue
        hit = methods & MUTATING_METHODS
        if hit:
            offenders.append((sorted(hit), path))
    assert offenders == [], (
        f"mutating routes exist outside /api and are NOT covered by "
        f"viewer_readonly_guard: {offenders}. Mount them under /api on "
        "_api_router (main.py), or extend the guard's wiring plus this "
        "test's exemption together."
    )


@pytest.mark.asyncio
async def test_viewer_is_refused_every_non_allowlisted_mutation(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    await _add(db_session_with_schema, "viewer@acme.com", Role.VIEWER)
    await _login(api_client_unauth, "viewer@acme.com")

    refused, allowed_through = [], []
    for method, path in _mutating_routes():
        # Concrete ids do not need to exist: the guard runs before the
        # handler, so a refusal is 403 regardless of whether the row is
        # there. Anything NOT 403 means the guard let it reach the handler.
        concrete = path.replace("{application_id}", "1").replace("{job_id}", "1")
        concrete = concrete.replace("{candidate_id}", "1").replace("{user_id}", "1")
        r = await api_client_unauth.request(method, concrete, json={})
        (refused if r.status_code == 403 else allowed_through).append(f"{method} {path}")

    assert allowed_through == [], f"viewer reached these mutations: {allowed_through}"
    assert refused


@pytest.mark.asyncio
async def test_recruiter_is_not_refused_by_the_guard(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    """The mirror image. Without it, a guard that refused EVERYONE would
    pass the test above and break the product."""
    await _add(db_session_with_schema, "rec@acme.com", Role.RECRUITER)
    await _login(api_client_unauth, "rec@acme.com")

    r = await api_client_unauth.patch("/api/applications/999999", json={"notes": "x"})

    # 404 (no such application) proves the guard let it through to the
    # handler. 403 would mean the guard wrongly refused a recruiter.
    assert r.status_code != 403


@pytest.mark.asyncio
async def test_every_allowlisted_route_is_reachable_by_a_viewer(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    """Otherwise the allowlist could be quietly empty and the suite would
    still pass — a viewer would simply have no chat and no password change."""
    await _add(db_session_with_schema, "viewer2@acme.com", Role.VIEWER)
    await _login(api_client_unauth, "viewer2@acme.com")

    r = await api_client_unauth.post(
        "/api/auth/password",
        json={"current_password": "pw-12345678", "new_password": "new-pw-12345"},
    )

    assert r.status_code == 204

    # Chat is the allowlist entry that matters most and the easiest to
    # lose in a refactor — without it a viewer account is worth very
    # little. Any status EXCEPT 403 proves the guard let it through to the
    # handler; 404 is the expected answer here since application 999999
    # does not exist, and asserting "not 403" avoids depending on an LLM.
    chat = await api_client_unauth.post(
        "/api/applications/999999/chat", json={"message": "hello"},
    )

    assert chat.status_code != 403

    # Logout is allowlisted too: deleting that entry breaks no other test
    # while a viewer silently loses the ability to log out.
    logout = await api_client_unauth.post("/api/auth/logout")

    assert logout.status_code != 403


@pytest.mark.asyncio
async def test_anonymous_callers_still_reach_login(
    api_client_unauth: AsyncClient,
) -> None:
    """The guard enforces role, not authentication. If it demanded a user
    it would 403 the login endpoint and lock everyone out."""
    r = await api_client_unauth.post(
        "/api/auth/login/password", json={"email": "nobody@acme.com", "password": "x"},
    )

    assert r.status_code == 401  # rejected by the handler, not the guard


@pytest.mark.asyncio
async def test_a_brand_new_mutating_route_is_denied_without_being_listed(
    db_session_with_schema: AsyncSession,
) -> None:
    """THE load-bearing test. Default-deny means a route nobody thought
    about is refused. If this is ever deleted, the design's whole promise
    is gone and nothing else would notice.

    The probe app mirrors main.py's ACTUAL wiring: the guard lives on an
    `APIRouter(dependencies=[Depends(viewer_readonly_guard)])` that the
    route is registered on, `include_router`ed into a plain `FastAPI()`
    with no dependencies of its own — not `FastAPI(dependencies=[...])`
    directly. Testing the latter would exercise the guard's LOGIC without
    exercising the WIRING main.py depends on; a future `_api_router =
    APIRouter()` with the dependency dropped would then still pass this
    test while shipping wide open.
    """
    from recruiter.api.deps import get_session

    guarded_router = APIRouter(dependencies=[Depends(viewer_readonly_guard)])

    @guarded_router.post("/api/invented/tomorrow")
    async def invented() -> dict:
        return {"reached": True}

    probe = FastAPI()
    probe.include_router(guarded_router)

    viewer = await _add(db_session_with_schema, "viewer3@acme.com", Role.VIEWER)

    async def _session_override():
        yield db_session_with_schema

    probe.dependency_overrides[get_session] = _session_override
    from recruiter.api.deps import maybe_user

    probe.dependency_overrides[maybe_user] = lambda: viewer

    async with AsyncClient(
        transport=ASGITransport(app=probe), base_url="http://test",
    ) as client:
        r = await client.post("/api/invented/tomorrow", json={})

    assert r.status_code == 403
    assert r.json()["detail"] == "read-only role"
