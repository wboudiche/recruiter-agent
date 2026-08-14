"""require_role has no route wired to it yet (Task 3 does that), so it
needs direct coverage now rather than shipping unverified. Exercises the
guard in isolation via dependency_overrides on require_user — the same
pattern test_auth_deps.py uses — rather than a real cookie/session, since
require_user's own 401 path is already covered elsewhere (test_auth_deps.py,
test_password_login_users.py's deactivation test) and is untouched by this
layer.
"""

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from recruiter.api.deps import require_role, require_user
from recruiter.models import Role, User


def _make_user(role: Role, *, is_active: bool = True) -> User:
    return User(id=1, email="u@acme.com", role=role, is_active=is_active)


def _build_app(*allowed: Role) -> FastAPI:
    app = FastAPI()

    @app.get("/gated")
    async def gated(user: User = Depends(require_role(*allowed))):
        return {"email": user.email, "role": user.role.value}

    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [Role.ADMIN, Role.RECRUITER, Role.VIEWER])
async def test_allowed_role_passes_through_and_returns_the_user(role: Role) -> None:
    app = _build_app(Role.ADMIN, Role.RECRUITER, Role.VIEWER)
    app.dependency_overrides[require_user] = lambda: _make_user(role)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/gated")

    assert r.status_code == 200
    assert r.json() == {"email": "u@acme.com", "role": role.value}


@pytest.mark.asyncio
async def test_disallowed_role_raises_403_with_insufficient_role_detail() -> None:
    app = _build_app(Role.ADMIN)
    app.dependency_overrides[require_user] = lambda: _make_user(Role.VIEWER)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/gated")

    assert r.status_code == 403
    assert r.json()["detail"] == "insufficient role"


@pytest.mark.asyncio
async def test_role_outside_the_allowed_set_is_refused_even_when_active_and_valid() -> None:
    # RECRUITER is a perfectly legitimate, active user — just not in this
    # particular route's allowed set (ADMIN, VIEWER). Confirms require_role
    # checks set membership, not merely "did require_user succeed".
    app = _build_app(Role.ADMIN, Role.VIEWER)
    app.dependency_overrides[require_user] = lambda: _make_user(Role.RECRUITER, is_active=True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/gated")

    assert r.status_code == 403
    assert r.json()["detail"] == "insufficient role"
