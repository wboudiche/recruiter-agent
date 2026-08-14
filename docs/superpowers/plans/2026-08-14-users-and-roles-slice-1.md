# Users and Roles (Slice 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let more than one person use the app, each with a role, and stop non-admins from reading or writing stored credentials.

**Architecture:** `users` gains `password_hash`, `role`, and `is_active`. Password login checks the users table first and keeps the existing env pair as a break-glass fallback. A `require_role(*roles)` dependency layers on the existing `require_user`, and Slice 1 applies it to five named routes plus a new admin-only `/api/users` router. A Users tab in Settings drives it.

**Tech Stack:** FastAPI + SQLAlchemy 2 (async) + Alembic + Pydantic v2; `argon2-cffi` for hashing; React 18 + TanStack Query + Vitest on the frontend.

## Global Constraints

- Python line length ≤ 100 chars (ruff `E501`). Match existing style; do not reformat untouched lines.
- Run every command from the repo root `/home/walidboudiche/recruiter-agent`.
- Backend tests: `.venv/bin/python -m pytest`. Frontend tests: `npm test --prefix recruiter-frontend`. Types: `npm run --prefix recruiter-frontend lint` (this is `tsc --noEmit`; there is **no** `typecheck` script).
- Ruff bar: no NEW errors in touched files versus baseline. The repo has many pre-existing ones (mostly `B008`); get a baseline with `git stash` if unsure.
- Do NOT change the session cookie name, TTL, or `auth_sessions` schema. Existing sessions must survive the upgrade.
- The OIDC path stays untouched. OIDC users keep `password_hash = NULL`.
- Commit after each task. Branch is `feat/users-and-roles`.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/recruiter/models/user.py` | `Role` enum + three new columns | Modify |
| `src/recruiter/models/__init__.py` | Export `Role` | Modify |
| `alembic/versions/20260814_000000_users_roles.py` | Columns, backfill, seed | Create |
| `src/recruiter/auth/passwords.py` | argon2 wrapper — the only file that knows the algorithm | Create |
| `src/recruiter/auth/dev_bypass.py` | Synthetic user needs a role | Modify |
| `src/recruiter/api/auth.py` | DB-first login, self-service password change | Modify |
| `src/recruiter/api/deps.py` | `require_role`, `is_active` check | Modify |
| `src/recruiter/schemas/auth.py` | `role` on `UserRead`; password payloads | Modify |
| `src/recruiter/schemas/user.py` | Admin user CRUD schemas | Create |
| `src/recruiter/api/users.py` | Admin-only `/api/users` router | Create |
| `src/recruiter/main.py` | Mount the users router | Modify |
| `src/recruiter/api/settings.py`, `sourcing.py` | Admin gate on 4 credential routes | Modify |
| `recruiter-frontend/src/hooks/use-users.ts` | Users queries + mutations | Create |
| `recruiter-frontend/src/components/settings/users-tab.tsx` | Admin UI | Create |
| `recruiter-frontend/src/components/settings/profile-tab.tsx` | Change-password form | Modify |
| `recruiter-frontend/src/routes/settings.tsx` | Conditional tab | Modify |

---

### Task 1: Role enum, columns, and migration

**Files:**
- Modify: `src/recruiter/models/user.py`, `src/recruiter/models/__init__.py`
- Create: `alembic/versions/20260814_000000_users_roles.py`
- Create: `src/recruiter/auth/passwords.py`
- Modify: `pyproject.toml` (add `argon2-cffi`)
- Test: `tests/unit/test_passwords.py`, `tests/api/test_users_migration.py`

**Interfaces:**
- Produces:
  - `Role` (str Enum) with members `ADMIN = "admin"`, `RECRUITER = "recruiter"`, `VIEWER = "viewer"`, exported from `recruiter.models`
  - `User.password_hash: str | None`, `User.role: Role`, `User.is_active: bool`
  - `hash_password(plain: str) -> str`
  - `verify_password(plain: str, hashed: str | None) -> bool`
  - `needs_rehash(hashed: str) -> bool`
  - `DUMMY_HASH: str` — a module-level precomputed hash used to burn time on unknown-email logins

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, add to `dependencies` after `"cryptography>=42",`:

```toml
  "argon2-cffi>=23.1",
```

Then install: `.venv/bin/python -m pip install "argon2-cffi>=23.1"`

- [ ] **Step 2: Write the failing password-module test**

Create `tests/unit/test_passwords.py`:

```python
"""The hashing wrapper is the only file that knows the algorithm.
Everything else calls these three functions."""

from recruiter.auth.passwords import (
    DUMMY_HASH, hash_password, needs_rehash, verify_password,
)


def test_hash_then_verify_roundtrips() -> None:
    hashed = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", hashed) is True


def test_wrong_password_is_rejected() -> None:
    hashed = hash_password("right")

    assert verify_password("wrong", hashed) is False


def test_hashes_are_salted() -> None:
    """Two users with the same password must not share a hash — otherwise
    a single crack, or even a glance at the column, reveals the collision."""
    assert hash_password("same") != hash_password("same")


def test_verify_against_missing_hash_is_false_not_an_error() -> None:
    """OIDC users have password_hash = NULL. The login path must treat that
    as 'wrong password', never as a crash or an accidental success."""
    assert verify_password("anything", None) is False


def test_dummy_hash_verifies_against_nothing() -> None:
    """DUMMY_HASH exists to burn the same CPU as a real verify on the
    unknown-email path, so timing cannot enumerate accounts."""
    assert verify_password("anything at all", DUMMY_HASH) is False


def test_needs_rehash_is_false_for_a_fresh_hash() -> None:
    assert needs_rehash(hash_password("fresh")) is False
```

- [ ] **Step 3: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_passwords.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'recruiter.auth.passwords'`

- [ ] **Step 4: Implement the password module**

Create `src/recruiter/auth/passwords.py`:

```python
"""Password hashing. The ONLY module that knows which algorithm is used —
callers see three functions, so changing algorithm touches one file.

argon2id via argon2-cffi: OWASP's default recommendation, and it handles
salting, encoding, verification, and rehash detection itself rather than
leaving those to call sites.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()

# Burned on the unknown-email login path so that "no such user" costs the
# same wall-clock as "wrong password". Without it, ~1ms vs ~50ms tells an
# attacker which emails have accounts — reinstating the enumeration oracle
# that identical 401 bodies exist to close.
DUMMY_HASH = _hasher.hash("not-a-real-password")


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str | None) -> bool:
    """False rather than raising for every failure mode.

    `hashed` is None for OIDC users, who have no password. A malformed
    hash (hand-edited DB row) is also a failure, not a crash.
    """
    if not hashed:
        return False
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    try:
        return _hasher.check_needs_rehash(hashed)
    except InvalidHashError:
        return True
```

- [ ] **Step 5: Run the password tests**

Run: `.venv/bin/python -m pytest tests/unit/test_passwords.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 6: Add the Role enum and columns**

In `src/recruiter/models/user.py`, add the import and enum above `class User`:

```python
from enum import Enum


class Role(str, Enum):
    ADMIN = "admin"          # manage users + credential-bearing settings
    RECRUITER = "recruiter"  # recruiting work; Slice 2 defines the boundary
    VIEWER = "viewer"        # read-only; enforced in Slice 2
```

Add three columns to `User`, after `picture`:

```python
    # NULL for OIDC users, who never have a password.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    # No DB default on purpose: creating a user must state the role, so a
    # code path that forgets cannot silently grant recruiting rights.
    role: Mapped[Role] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
```

Extend the SQLAlchemy import on line 4 to include `Boolean`.

In `src/recruiter/models/__init__.py`, import `Role` from `recruiter.models.user` and add `"Role"` to `__all__`, keeping both lists alphabetical.

- [ ] **Step 7: Write the failing migration test**

Create `tests/api/test_users_migration.py`:

```python
"""The migration must leave a working deployment working: existing users
keep full access, and the env account becomes a real, usable admin row."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.auth.passwords import verify_password
from recruiter.models import Role, User


@pytest.mark.asyncio
async def test_columns_exist_with_working_defaults(
    db_session_with_schema: AsyncSession,
) -> None:
    user = User(email="a@acme.com", role=Role.RECRUITER)
    db_session_with_schema.add(user)
    await db_session_with_schema.commit()

    fetched = (await db_session_with_schema.execute(
        select(User).where(User.email == "a@acme.com")
    )).scalar_one()

    assert fetched.role == Role.RECRUITER
    assert fetched.is_active is True
    assert fetched.password_hash is None


@pytest.mark.asyncio
async def test_password_hash_roundtrips_through_the_column(
    db_session_with_schema: AsyncSession,
) -> None:
    from recruiter.auth.passwords import hash_password

    db_session_with_schema.add(
        User(email="b@acme.com", role=Role.ADMIN, password_hash=hash_password("s3cret")),
    )
    await db_session_with_schema.commit()

    fetched = (await db_session_with_schema.execute(
        select(User).where(User.email == "b@acme.com")
    )).scalar_one()

    assert verify_password("s3cret", fetched.password_hash) is True
    assert verify_password("wrong", fetched.password_hash) is False
```

- [ ] **Step 8: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/api/test_users_migration.py -v`
Expected: FAIL — the `users` table has no `role` column yet (the test schema is built from the models, so this fails until Step 6 is present AND the migration exists for real deployments).

If Step 6 is already committed the model-built test schema may pass; the migration in Step 9 is still required, because production databases are migrated, not recreated.

- [ ] **Step 9: Write the migration**

Find the current head first: `.venv/bin/python -m alembic heads`

Create `alembic/versions/20260814_000000_users_roles.py`, replacing `<CURRENT_HEAD>` with what that command printed:

```python
"""users: password_hash, role, is_active + seed the first admin

Revision ID: 7c1e9a4d2b58
Revises: <CURRENT_HEAD>
Create Date: 2026-08-14 00:00:00.000000

Until now the deployment supported exactly one human: the password login
compared against a single env pair and User rows only came from OIDC.
This adds per-user credentials and roles.

Existing rows are backfilled to `admin` deliberately — those users were
unrestricted before this migration, and silently demoting them to viewer
would break a working deployment on upgrade.
"""
import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '7c1e9a4d2b58'
down_revision: Union[str, None] = '<CURRENT_HEAD>'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("role", sa.String(32), nullable=True))
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    # Backfill BEFORE the NOT NULL constraint, or existing rows reject it.
    op.execute("UPDATE users SET role = 'admin' WHERE role IS NULL")
    op.alter_column("users", "role", nullable=False)

    conn = op.get_bind()
    email = (os.environ.get("RECRUITER_DEFAULT_ACCOUNT_EMAIL") or "").strip().lower()
    password = os.environ.get("RECRUITER_DEFAULT_ACCOUNT_PASSWORD") or ""
    existing = conn.execute(sa.text("SELECT count(*) FROM users")).scalar_one()

    if not email or not password:
        if existing == 0:
            # Seeding nothing here leaves a deployment with zero accounts and,
            # without OIDC, no way in. Fail loudly instead of locking the
            # operator out silently.
            raise RuntimeError(
                "users/roles migration: no users exist and "
                "RECRUITER_DEFAULT_ACCOUNT_EMAIL/PASSWORD are unset — "
                "set them so a first admin can be seeded, then re-run."
            )
        return

    already = conn.execute(
        sa.text("SELECT count(*) FROM users WHERE lower(email) = :e"), {"e": email},
    ).scalar_one()
    if already:
        # Idempotent: an existing row (e.g. from a previous password login)
        # is promoted rather than duplicated.
        conn.execute(
            sa.text("UPDATE users SET role = 'admin', is_active = true "
                    "WHERE lower(email) = :e"),
            {"e": email},
        )
        return

    from recruiter.auth.passwords import hash_password

    conn.execute(
        sa.text(
            "INSERT INTO users (email, sub, issuer, name, role, is_active, password_hash) "
            "VALUES (:e, :sub, 'default', 'Admin', 'admin', true, :h)"
        ),
        {"e": email, "sub": f"default:{email}", "h": hash_password(password)},
    )


def downgrade() -> None:
    op.drop_column("users", "is_active")
    op.drop_column("users", "role")
    op.drop_column("users", "password_hash")
```

- [ ] **Step 10: Give the dev-bypass user a role**

Every existing API test authenticates through dev bypass, so its synthetic user must have a role or the whole suite fails on a NOT NULL violation.

In `src/recruiter/auth/dev_bypass.py`, change the `User(...)` construction to:

```python
    user = User(email=email, sub=f"dev-bypass:{email}", issuer="dev-bypass",
                name="Dev User", role=Role.ADMIN)
```

and add `Role` to the models import. Admin is correct here: the bypass exists to make local development frictionless, and it only activates when no IdP is configured.

- [ ] **Step 11: Run the full backend suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass. If anything fails with a NOT NULL violation on `role`, some code path creates a `User` without one — find it and give it an explicit role rather than adding a column default.

- [ ] **Step 12: Verify the migration against a real database, twice**

The unit tests above build their schema from the models, so they prove the
columns work but never execute the migration. Run it for real, and run it
twice — the seed must be idempotent, or a re-run creates a duplicate admin
or fails on the unique email index.

```bash
docker compose up -d postgres
.venv/bin/python -m alembic upgrade head
docker compose exec -T postgres psql -U recruiter -d recruiter -c "\d users"
docker compose exec -T postgres psql -U recruiter -d recruiter \
  -c "select email, role, is_active, password_hash is not null as has_pw from users;"

# Idempotency: re-running the whole chain must not duplicate the seed.
.venv/bin/python -m alembic downgrade -1
.venv/bin/python -m alembic upgrade head
docker compose exec -T postgres psql -U recruiter -d recruiter \
  -c "select count(*) from users where role = 'admin';"
```

Expected: `password_hash`, `role` (not null), `is_active` (not null, default
true) present; the `.env` account seeded with `role = admin` and `has_pw = t`;
and the admin count **unchanged** after the second upgrade.

Record the observed admin count before and after in your report — "it ran
without error" is not evidence of idempotency.

- [ ] **Step 13: Commit**

```bash
git add pyproject.toml src/recruiter/models/user.py src/recruiter/models/__init__.py \
        src/recruiter/auth/passwords.py src/recruiter/auth/dev_bypass.py \
        alembic/versions/20260814_000000_users_roles.py \
        tests/unit/test_passwords.py tests/api/test_users_migration.py
git commit -m "feat(auth): add role, password_hash and is_active to users"
```

---

### Task 2: DB-backed login, deactivation, and require_role

**Files:**
- Modify: `src/recruiter/api/auth.py:220-260`, `src/recruiter/api/deps.py:37`
- Modify: `src/recruiter/schemas/auth.py`
- Test: `tests/api/test_password_login_users.py` (create)

**Interfaces:**
- Consumes: `Role`, `User.password_hash`, `User.is_active`, `hash_password`, `verify_password`, `needs_rehash`, `DUMMY_HASH` from Task 1.
- Produces:
  - `require_role(*allowed: Role)` in `api/deps.py` — returns a FastAPI dependency yielding `User`, raising 403 `"insufficient role"`
  - `UserRead.role: Role`
  - `POST /api/auth/password` accepting `{"current_password": str, "new_password": str}`

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_password_login_users.py`:

```python
"""Login moves from a single env pair to the users table. The env pair
survives as break-glass.

The three failure modes below MUST be indistinguishable. If unknown-email
and wrong-password differ in status, body, or (via the dummy verify) rough
timing, the login page becomes an account-enumeration oracle.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.auth.passwords import hash_password
from recruiter.models import Role, User


async def _add_user(
    session: AsyncSession, email: str, password: str | None = "pw",
    role: Role = Role.RECRUITER, is_active: bool = True,
) -> User:
    user = User(
        email=email, role=role, is_active=is_active,
        password_hash=hash_password(password) if password else None,
    )
    session.add(user)
    await session.commit()
    return user


@pytest.mark.asyncio
async def test_user_from_the_table_can_log_in(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    await _add_user(db_session_with_schema, "recruiter@acme.com", "s3cret")

    r = await api_client_unauth.post(
        "/api/auth/login/password",
        json={"email": "recruiter@acme.com", "password": "s3cret"},
    )

    assert r.status_code == 204
    assert "recruiter_session" in r.cookies


@pytest.mark.asyncio
async def test_wrong_password_unknown_email_and_deactivated_are_identical(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    await _add_user(db_session_with_schema, "real@acme.com", "s3cret")
    await _add_user(db_session_with_schema, "gone@acme.com", "s3cret", is_active=False)

    wrong = await api_client_unauth.post(
        "/api/auth/login/password",
        json={"email": "real@acme.com", "password": "nope"},
    )
    unknown = await api_client_unauth.post(
        "/api/auth/login/password",
        json={"email": "nobody@acme.com", "password": "nope"},
    )
    disabled = await api_client_unauth.post(
        "/api/auth/login/password",
        json={"email": "gone@acme.com", "password": "s3cret"},
    )

    assert wrong.status_code == unknown.status_code == disabled.status_code == 401
    assert wrong.json() == unknown.json() == disabled.json()


@pytest.mark.asyncio
async def test_oidc_user_without_a_password_cannot_use_the_form(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    await _add_user(db_session_with_schema, "sso@acme.com", password=None)

    r = await api_client_unauth.post(
        "/api/auth/login/password",
        json={"email": "sso@acme.com", "password": ""},
    )

    assert r.status_code == 401
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/api/test_password_login_users.py -v`
Expected: FAIL — the table user gets 401 because login still only compares the env pair.

- [ ] **Step 3: Rewrite the login handler**

In `src/recruiter/api/auth.py`, replace the body of `login_password` after the `cfg = get_config()` line with:

```python
    email = payload.email.strip().lower()
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()

    # Always verify SOMETHING. On unknown email we burn the same CPU against
    # a dummy hash so "no such account" and "wrong password" cost the same —
    # otherwise timing re-opens the enumeration hole that the identical 401
    # bodies below exist to close.
    stored = user.password_hash if user and user.is_active else None
    password_ok = verify_password(payload.password, stored or DUMMY_HASH) and stored is not None

    if password_ok and user is not None:
        if needs_rehash(user.password_hash or ""):
            user.password_hash = hash_password(payload.password)
        await _issue_session(session, request, user)
        return Response(status_code=204)

    # Break-glass: the env pair still authenticates, resolving to the seeded
    # admin row. Kept so an operator who loses every admin password can
    # recover without hand-editing the database.
    if cfg.default_account_email and cfg.default_account_password:
        email_ok = secrets.compare_digest(
            email.encode("utf-8"),
            cfg.default_account_email.strip().lower().encode("utf-8"),
        )
        pw_ok = secrets.compare_digest(
            payload.password.encode("utf-8"),
            cfg.default_account_password.encode("utf-8"),
        )
        if email_ok and pw_ok:
            fallback = await _resolve_break_glass_admin(session, cfg)
            await _issue_session(session, request, fallback)
            return Response(status_code=204)

    # One message for every failure: wrong password, unknown email, and
    # deactivated account are indistinguishable to the caller.
    raise HTTPException(status_code=401, detail="invalid credentials")
```

Extract the existing session-issuing tail (the `create_session` call and cookie set, currently at the end of the handler) into `_issue_session(session, request, user)`, and the existing "find or create the default-account user" block into `_resolve_break_glass_admin(session, cfg)`, giving the created user `role=Role.ADMIN`. Add the imports: `Role`, `DUMMY_HASH`, `hash_password`, `needs_rehash`, `verify_password`.

- [ ] **Step 4: Run the login tests**

Run: `.venv/bin/python -m pytest tests/api/test_password_login_users.py tests/api/test_password_login.py -v`
Expected: PASS — including the pre-existing env-pair test, which now exercises the break-glass path.

- [ ] **Step 5: Write the failing deactivation + role tests**

Append to `tests/api/test_password_login_users.py`:

```python
@pytest.mark.asyncio
async def test_deactivation_kills_an_existing_session_immediately(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    """Sessions last days. If deactivation only stopped NEW logins, a
    dismissed user would keep full access until their cookie expired."""
    user = await _add_user(db_session_with_schema, "temp@acme.com", "s3cret")
    await api_client_unauth.post(
        "/api/auth/login/password",
        json={"email": "temp@acme.com", "password": "s3cret"},
    )
    assert (await api_client_unauth.get("/api/auth/me")).status_code == 200

    user.is_active = False
    await db_session_with_schema.commit()

    assert (await api_client_unauth.get("/api/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_me_exposes_role_so_the_ui_can_render_itself(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    await _add_user(db_session_with_schema, "boss@acme.com", "s3cret", role=Role.ADMIN)
    await api_client_unauth.post(
        "/api/auth/login/password",
        json={"email": "boss@acme.com", "password": "s3cret"},
    )

    body = (await api_client_unauth.get("/api/auth/me")).json()

    assert body["role"] == "admin"
    # The docstring on UserRead forbids leaking IdP correlation keys.
    assert "sub" not in body and "issuer" not in body
```

- [ ] **Step 6: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/api/test_password_login_users.py -v`
Expected: FAIL — deactivated session still returns 200, and `/me` has no `role`.

- [ ] **Step 7: Enforce is_active and expose role**

In `src/recruiter/api/deps.py`, inside `require_user`, immediately after `user = await lookup_session(...)` and its None check:

```python
    if not user.is_active:
        # Deactivation must bite now, not at cookie expiry.
        raise HTTPException(status_code=401, detail="session expired")
```

Apply the same check to the `bypass_user` early return.

Add the role guard at the end of `deps.py`:

```python
def require_role(*allowed: Role):
    """Gate a route on role. Layers on `require_user`, so the 401 path is
    unchanged and only the 403 is new."""

    async def _guard(user: User = Depends(require_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail="insufficient role")
        return user

    return _guard
```

Import `Role` from `recruiter.models`.

In `src/recruiter/schemas/auth.py`, add to `UserRead` after `picture`:

```python
    # The client needs its own authorization level to render navigation.
    # This is NOT an IdP correlation key, so it does not violate the rule
    # above about `sub`/`issuer`. `is_active` is deliberately absent: an
    # inactive user cannot hold a session, so it would always be true.
    role: Role
```

- [ ] **Step 8: Run the full backend suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add src/recruiter/api/auth.py src/recruiter/api/deps.py src/recruiter/schemas/auth.py \
        tests/api/test_password_login_users.py
git commit -m "feat(auth): authenticate against the users table, honour is_active, add require_role"
```

---

### Task 3: Admin user API and the credential gate

**Files:**
- Create: `src/recruiter/api/users.py`, `src/recruiter/schemas/user.py`
- Modify: `src/recruiter/main.py`, `src/recruiter/api/settings.py:70`, `src/recruiter/api/sourcing.py:183,222,259`, `src/recruiter/api/auth.py`
- Test: `tests/api/test_users_api.py` (create)

**Interfaces:**
- Consumes: `require_role`, `Role`, `hash_password`, `revoke_session` semantics from Tasks 1-2.
- Produces: `GET /api/users`, `POST /api/users`, `PATCH /api/users/{id}`, `POST /api/users/{id}/password`, `POST /api/auth/password`.

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_users_api.py`:

```python
"""Admin-only user management, plus the guard rails that stop an admin
locking everyone out of the install."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.auth.passwords import hash_password, verify_password
from recruiter.models import Role, User


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

    admin_client_cookies = api_client_unauth.cookies.copy()
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
    assert admin_client_cookies is not None


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
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/api/test_users_api.py -v`
Expected: FAIL — `/api/users` is 404, and the credential routes still return 200 for a recruiter.

- [ ] **Step 3: Write the schemas**

Create `src/recruiter/schemas/user.py`:

```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from recruiter.models import Role


class UserAdminRead(BaseModel):
    """Admin projection. Deliberately omits `password_hash` — a hash must
    never leave the server, not even to an admin."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str | None
    role: Role
    is_active: bool
    last_login_at: datetime | None


class UserCreate(BaseModel):
    email: EmailStr
    name: str | None = None
    role: Role
    password: str = Field(min_length=8)


class UserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


class PasswordSet(BaseModel):
    password: str = Field(min_length=8)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)
```

- [ ] **Step 4: Write the users router**

Create `src/recruiter/api/users.py`:

```python
"""Admin-only user management.

No DELETE by design: `event_logs` and `auth_sessions` reference users, so
hard deletion either cascades away audit history or fails on a foreign
key. Deactivation is the supported removal.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.deps import get_session, require_role
from recruiter.auth.passwords import hash_password
from recruiter.models import AuthSession, Role, User
from recruiter.schemas.user import PasswordSet, UserAdminRead, UserCreate, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])


async def _active_admin_count(session: AsyncSession, *, excluding: int) -> int:
    return (await session.execute(
        select(func.count())
        .select_from(User)
        .where(User.role == Role.ADMIN, User.is_active.is_(True), User.id != excluding)
    )).scalar_one()


@router.get("", response_model=list[UserAdminRead])
async def list_users(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(Role.ADMIN)),
) -> list[UserAdminRead]:
    rows = (await session.execute(select(User).order_by(User.email))).scalars().all()
    return [UserAdminRead.model_validate(r) for r in rows]


@router.post("", response_model=UserAdminRead, status_code=201)
async def create_user(
    payload: UserCreate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(Role.ADMIN)),
) -> UserAdminRead:
    email = payload.email.strip().lower()
    if (await session.execute(select(User).where(User.email == email))).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="a user with that email already exists")
    user = User(
        email=email, name=payload.name, role=payload.role, is_active=True,
        password_hash=hash_password(payload.password),
    )
    session.add(user)
    await session.commit()
    return UserAdminRead.model_validate(user)


@router.patch("/{user_id}", response_model=UserAdminRead)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_role(Role.ADMIN)),
) -> UserAdminRead:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    if payload.is_active is False and user.id == actor.id:
        raise HTTPException(status_code=409, detail="you cannot deactivate yourself")

    loses_admin = (
        user.role == Role.ADMIN
        and user.is_active
        and (payload.role not in (None, Role.ADMIN) or payload.is_active is False)
    )
    if loses_admin and await _active_admin_count(session, excluding=user.id) == 0:
        raise HTTPException(
            status_code=409,
            detail="this is the last active admin — promote another admin first",
        )

    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
        if payload.is_active is False:
            # Deactivation must bite now, not at cookie expiry.
            await session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    await session.commit()
    return UserAdminRead.model_validate(user)


@router.post("/{user_id}/password", status_code=204)
async def reset_password(
    user_id: int,
    payload: PasswordSet,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(Role.ADMIN)),
) -> None:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    user.password_hash = hash_password(payload.password)
    # A reset exists to cut off access; old cookies must not survive it.
    await session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    await session.commit()
```

Mount it in `src/recruiter/main.py` alongside the other routers: `app.include_router(users.router)` with `from recruiter.api import users`.

- [ ] **Step 5: Add self-service password change**

In `src/recruiter/api/auth.py`:

```python
@router.post("/password", status_code=204)
async def change_own_password(
    payload: PasswordChange,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> None:
    """Any role may change their OWN password. Without this the admin who
    created the account knows its password forever."""
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=403, detail="current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    await session.commit()
```

Import `PasswordChange` from `recruiter.schemas.user` and `require_user` from `recruiter.api.deps`.

- [ ] **Step 6: Gate the four credential routes**

Add `_: User = Depends(require_role(Role.ADMIN))` as a parameter to each of:

- `src/recruiter/api/settings.py:70` — `update_settings` (the `PUT ""` handler)
- `src/recruiter/api/sourcing.py:183` — `linkedin_connect`
- `src/recruiter/api/sourcing.py:222` — `linkedin_connect_cookie`
- `src/recruiter/api/sourcing.py:259` — `linkedin_disconnect`

Leave `GET ""` in settings and the `/search` + `/query/suggest` sourcing routes on plain `require_user`: the notify wizard reads settings for the recruiter's name and email, and search is ordinary recruiting work.

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/api/test_users_api.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 8: Run the full backend suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass. Existing settings tests use the dev-bypass user, which Task 1 gave `Role.ADMIN`, so they still reach `PUT /api/settings`.

- [ ] **Step 9: Commit**

```bash
git add src/recruiter/api/users.py src/recruiter/schemas/user.py src/recruiter/main.py \
        src/recruiter/api/auth.py src/recruiter/api/settings.py src/recruiter/api/sourcing.py \
        tests/api/test_users_api.py
git commit -m "feat(api): admin-only user management and credential-route gate"
```

---

### Task 4: Users tab and change-password form

**Files:**
- Create: `recruiter-frontend/src/hooks/use-users.ts`, `recruiter-frontend/src/components/settings/users-tab.tsx`, `recruiter-frontend/src/components/settings/users-tab.test.tsx`
- Modify: `recruiter-frontend/src/components/settings/profile-tab.tsx`, `recruiter-frontend/src/routes/settings.tsx`, `recruiter-frontend/src/hooks/use-current-user.ts`

**Interfaces:**
- Consumes: the endpoints from Task 3, and `role` on `GET /api/auth/me` from Task 2.
- Produces: `useUsers()`, `useCreateUser()`, `useUpdateUser()`, `useResetPassword()` in `use-users.ts`; a `UsersTab` component.

- [ ] **Step 1: Write the failing test**

Create `recruiter-frontend/src/components/settings/users-tab.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { UsersTab } from "./users-tab";

const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: apiMock };
});

const USERS = [
  { id: 1, email: "boss@acme.com", name: "Boss", role: "admin", is_active: true, last_login_at: null },
  { id: 2, email: "rec@acme.com", name: null, role: "recruiter", is_active: true, last_login_at: null },
];

function renderTab() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <UsersTab />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiMock.mockReset();
  apiMock.mockImplementation((path: string) =>
    path === "/api/users" ? Promise.resolve(USERS) : Promise.resolve({}),
  );
});

describe("UsersTab", () => {
  it("lists users with their roles", async () => {
    renderTab();

    expect(await screen.findByText("boss@acme.com")).toBeInTheDocument();
    expect(screen.getByText("rec@acme.com")).toBeInTheDocument();
  });

  it("deactivates a user through PATCH", async () => {
    renderTab();
    await screen.findByText("rec@acme.com");

    await userEvent.click(screen.getByRole("button", { name: /deactivate rec@acme.com/i }));

    await waitFor(() =>
      expect(apiMock).toHaveBeenCalledWith("/api/users/2", {
        method: "PATCH",
        json: { is_active: false },
      }),
    );
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm test --prefix recruiter-frontend -- users-tab`
Expected: FAIL — `./users-tab` does not exist.

- [ ] **Step 3: Write the hooks**

Create `recruiter-frontend/src/hooks/use-users.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export interface UserAdminRead {
  id: number;
  email: string;
  name: string | null;
  role: "admin" | "recruiter" | "viewer";
  is_active: boolean;
  last_login_at: string | null;
}

const USERS_KEY = ["users"] as const;

export function useUsers() {
  return useQuery({
    queryKey: USERS_KEY,
    queryFn: () => api<UserAdminRead[]>("/api/users"),
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      email: string; name?: string; role: string; password: string;
    }) => api<UserAdminRead>("/api/users", { method: "POST", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: USERS_KEY }),
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number; role?: string; is_active?: boolean }) =>
      api<UserAdminRead>(`/api/users/${id}`, { method: "PATCH", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: USERS_KEY }),
  });
}

export function useResetPassword() {
  return useMutation({
    mutationFn: ({ id, password }: { id: number; password: string }) =>
      api(`/api/users/${id}/password`, { method: "POST", json: { password } }),
  });
}
```

- [ ] **Step 4: Write the Users tab**

Create `recruiter-frontend/src/components/settings/users-tab.tsx`. Use the
same primitives as the existing `sourcing-tab.tsx` (`Button`, plain labels,
Tailwind classes) so it matches the rest of Settings:

```tsx
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  useCreateUser, useResetPassword, useUpdateUser, useUsers,
} from "@/hooks/use-users";

const ROLES = ["admin", "recruiter", "viewer"] as const;

function fail(err: unknown, fallback: string) {
  // Surfaces the server's 409 guard-rail text ("this is the last active
  // admin — promote another admin first") verbatim, rather than replacing
  // it with a generic message that hides why the action was refused.
  toast.error(err instanceof ApiError ? err.detail : fallback);
}

export function UsersTab() {
  const users = useUsers();
  const createUser = useCreateUser();
  const updateUser = useUpdateUser();
  const resetPassword = useResetPassword();
  const [form, setForm] = useState({
    email: "", name: "", role: "recruiter", password: "",
  });

  return (
    <div className="space-y-6">
      <table className="w-full text-sm">
        <tbody>
          {(users.data ?? []).map((u) => (
            <tr key={u.id} className="border-b">
              <td className="py-2">
                <div>{u.email}</div>
                <div className="text-xs text-muted-foreground">{u.name ?? "—"}</div>
              </td>
              <td>
                <select
                  aria-label={`Role for ${u.email}`}
                  value={u.role}
                  onChange={(e) =>
                    updateUser.mutate(
                      { id: u.id, role: e.target.value },
                      { onError: (err) => fail(err, "Could not change role") },
                    )
                  }
                >
                  {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </td>
              <td>{u.is_active ? "active" : "inactive"}</td>
              <td className="space-x-2">
                <Button
                  size="sm"
                  variant="outline"
                  aria-label={`${u.is_active ? "Deactivate" : "Reactivate"} ${u.email}`}
                  onClick={() =>
                    updateUser.mutate(
                      { id: u.id, is_active: !u.is_active },
                      { onError: (err) => fail(err, "Could not update user") },
                    )
                  }
                >
                  {u.is_active ? "Deactivate" : "Reactivate"}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  aria-label={`Reset password for ${u.email}`}
                  onClick={() => {
                    const pw = window.prompt(`New password for ${u.email}`);
                    if (!pw) return;
                    resetPassword.mutate(
                      { id: u.id, password: pw },
                      {
                        onSuccess: () => toast.success("Password reset — their sessions were ended"),
                        onError: (err) => fail(err, "Could not reset password"),
                      },
                    );
                  }}
                >
                  Reset password
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          createUser.mutate(form, {
            onSuccess: () => {
              toast.success("User created");
              setForm({ email: "", name: "", role: "recruiter", password: "" });
            },
            onError: (err) => fail(err, "Could not create user"),
          });
        }}
      >
        <input
          aria-label="Email" type="email" required value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })}
        />
        <input
          aria-label="Name" value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <select
          aria-label="Role" value={form.role}
          onChange={(e) => setForm({ ...form, role: e.target.value })}
        >
          {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <input
          aria-label="Initial password" type="password" required minLength={8}
          value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })}
        />
        <Button type="submit" disabled={createUser.isPending}>Add user</Button>
      </form>
    </div>
  );
}
```

The `aria-label`s carrying the email are load-bearing: the test targets
`Deactivate rec@acme.com` specifically, so a row action can never be
ambiguous between users.

- [ ] **Step 5: Run the tab tests**

Run: `npm test --prefix recruiter-frontend -- users-tab`
Expected: PASS, 2 tests.

- [ ] **Step 6: Expose role and show the tab conditionally**

In `recruiter-frontend/src/hooks/use-current-user.ts`, add to the user type:

```ts
  role: "admin" | "recruiter" | "viewer";
```

In `recruiter-frontend/src/routes/settings.tsx`, import `useCurrentUser` and
`UsersTab`, then gate both the trigger and the panel on the role:

```tsx
  const me = useCurrentUser();
  const isAdmin = me.data?.role === "admin";
```

```tsx
          {isAdmin && <TabsTrigger value="users">Users</TabsTrigger>}
```

```tsx
          {isAdmin && (
            <TabsContent value="users">
              <UsersTab />
            </TabsContent>
          )}
```

Match the exact `TabsTrigger` / `TabsContent` idiom already used by the LLM
and Sourcing tabs in that file. This is cosmetic — Task 3's 403s are the
real gate; hiding a tab protects nothing on its own.

- [ ] **Step 7: Add the change-password form**

In `recruiter-frontend/src/components/settings/profile-tab.tsx`, add this
section, available to every role:

```tsx
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const changePassword = useMutation({
    mutationFn: () => api("/api/auth/password", { method: "POST", json: pw }),
    onSuccess: () => {
      toast.success("Password changed");
      setPw({ current_password: "", new_password: "" });
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Could not change password"),
  });
```

```tsx
      <form
        className="space-y-2"
        onSubmit={(e) => { e.preventDefault(); changePassword.mutate(); }}
      >
        <input
          aria-label="Current password" type="password" required
          value={pw.current_password}
          onChange={(e) => setPw({ ...pw, current_password: e.target.value })}
        />
        <input
          aria-label="New password" type="password" required minLength={8}
          value={pw.new_password}
          onChange={(e) => setPw({ ...pw, new_password: e.target.value })}
        />
        <Button type="submit" disabled={changePassword.isPending}>
          Change password
        </Button>
      </form>
```

Add the imports it needs: `useState`, `useMutation`, `toast`, `api`,
`ApiError`, `Button`.

- [ ] **Step 8: Run the full frontend suite and typecheck**

Run: `npm test --prefix recruiter-frontend && npm run --prefix recruiter-frontend lint`
Expected: all tests pass, no TypeScript errors.

- [ ] **Step 9: Commit**

```bash
git add recruiter-frontend/src
git commit -m "feat(settings): admin Users tab and self-service password change"
```

---

### Task 5: Verify the upgrade path on a real deployment

**Files:** none — manual verification against the running stack.

**Interfaces:** consumes everything from Tasks 1-4.

- [ ] **Step 1: Rebuild and restart**

```bash
docker compose build backend frontend && docker compose up -d --force-recreate
docker compose logs backend --tail 20
```

Expected: `applying alembic migrations...` succeeds. The seeded admin comes from `RECRUITER_DEFAULT_ACCOUNT_EMAIL` in `.env`.

- [ ] **Step 2: Confirm the existing session survived**

Open `http://localhost:8088`. You should still be logged in — this plan never changes the cookie or session table.

- [ ] **Step 3: Confirm the seeded admin**

```bash
docker compose exec -T postgres psql -U recruiter -d recruiter \
  -c "select id, email, role, is_active, password_hash is not null as has_pw from users;"
```

Expected: your `.env` account present with `role = admin` and `has_pw = t`.

- [ ] **Step 4: Create a second user and verify the gate**

In Settings → Users, add a user with role `recruiter`. Log out, log in as them, and confirm:
- the Users tab is absent
- `curl -b <their cookie> -X PUT localhost:8088/api/settings -d '{}' -H 'content-type: application/json'` returns **403**

- [ ] **Step 5: Verify deactivation bites immediately**

While the recruiter is logged in elsewhere, deactivate them from the admin account. Their very next request must return 401 — not at session expiry.

- [ ] **Step 6: Clean up**

Delete the test user row, or leave it deactivated if you want a second account.

- [ ] **Step 7: Commit any fixes**

If Steps 1-5 revealed a defect, fix it, re-run both suites, and commit. If everything passed, nothing to commit.

---

## Verification checklist

- [ ] `.venv/bin/python -m pytest -q` — green
- [ ] `npm test --prefix recruiter-frontend` — green
- [ ] `npm run --prefix recruiter-frontend lint` — clean
- [ ] `ruff check` on touched files — no new errors versus baseline
- [ ] Migration applies to an existing database and seeds the admin
- [ ] A recruiter receives 403 on `PUT /api/settings` and on `/api/users`
- [ ] Deactivation invalidates a live session on the next request
