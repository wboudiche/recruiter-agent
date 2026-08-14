# Users and roles — Slice 1

Date: 2026-08-14
Status: approved (design)
Scope: Slice 1 of 2. Slice 2 (full permission matrix) is a separate spec.

## Problem

The deployment supports exactly one human. `User` rows are only ever created
by OIDC login, and OIDC is off in the shipped compose
(`RECRUITER_OIDC_ISSUER: ""`). The password path (`api/auth.py:220`)
compares constant-time against a single `RECRUITER_DEFAULT_ACCOUNT_EMAIL` /
`RECRUITER_DEFAULT_ACCOUNT_PASSWORD` pair from the environment. There is no
role concept anywhere.

`api/applications.py:22-25` records this as a deliberate v1 decision, and
names the follow-up: "If per-user ownership or role tiers
(admin/recruiter/viewer) are ever needed, add a column on
Candidate/Application and a guard alongside `require_user`."

That need has arrived.

## Slicing

This spec is **Slice 1**: accounts, password authentication, roles, and an
admin lock on the sharpest surface. It ships something usable on its own —
more than one person can log in, and only admins can change API keys or
manage users.

**Slice 2** (separate spec) enforces the full permission matrix: viewer
genuinely read-only, recruiter blocked from admin surfaces, across all seven
routers. Roles exist in Slice 1 but only gate settings-mutation and user
management; recruiter and viewer are not yet differentiated from each other.
Half-enforcing a matrix across seven routers is worse than not starting.

**Slice 3** (not yet specced): email invitations with tokens and expiry.

## Design

### 1. Data model

`Role` follows the existing `Stage` pattern (`models/application.py:14`) —
`class Role(str, Enum)`, stored as a string column.

```
admin      manage users and settings; everything a recruiter can do
recruiter  all recruiting work (Slice 2 defines the boundary)
viewer     read-only (enforced in Slice 2)
```

`users` gains three columns:

| Column | Type | Constraint |
|---|---|---|
| `password_hash` | `str \| None` | Null for OIDC users, who never have one |
| `role` | `Role` | NOT NULL, **no DB default** |
| `is_active` | `bool` | NOT NULL, default `true` |

`role` is deliberately non-nullable with no default: creating a user forces
the caller to state the role. A default of `recruiter` means a bug that
skips role assignment silently grants recruiting rights.

No separate `roles` table. A three-value enum on `users` is the entire
requirement; a join table buys nothing until roles become per-job or
user-definable, and it is a cheap migration to add then.

### 2. Migration

One Alembic revision:

1. Adds the three columns. Backfills `role = admin` for existing rows —
   those users were unrestricted before this change, and silently demoting
   them to `viewer` breaks a working deployment on upgrade.
2. Seeds a user from `RECRUITER_DEFAULT_ACCOUNT_EMAIL` with `role = admin`
   and the env password hashed into `password_hash`, only when no row with
   that email exists. Safe to re-run.
3. **Fails loudly** if `RECRUITER_DEFAULT_ACCOUNT_EMAIL` is empty and the
   `users` table is empty. Seeding nothing in that state leaves a
   deployment with zero accounts and, without OIDC, no way in. A clear
   migration error beats a silent lockout.

Migrations already run on startup (`docker/backend-entrypoint.sh` runs
`alembic upgrade head` before uvicorn), so this needs no manual step.

### 3. Password storage

New dependency: `argon2-cffi` (OWASP default; handles salting, encoding,
verification, and rehash detection). The considered alternative — scrypt via
the existing `cryptography` — was rejected because it means hand-rolling
salt storage and encoding in security-critical code.

A single module `recruiter/auth/passwords.py` exposes `hash_password`,
`verify_password`, and `needs_rehash`. Confining the library to one module
means changing the algorithm later touches one file.

### 4. Authentication

`POST /api/auth/login/password` keeps its existing
`@limiter.limit("5/minute")` and its cookie contract. Lookup order:

1. **Users table** — by email, requiring `is_active` and a non-null
   `password_hash`; verify with argon2.
2. **Env break-glass** — the existing constant-time comparison, resolving
   to the seeded admin row.

Both paths end at `create_session(...)` exactly as today. No change to
session storage, TTL, or the cookie, so existing sessions survive the
upgrade.

Three security requirements, each with the failure it prevents:

- **Identical failures.** Unknown email, wrong password, and deactivated
  account return the same 401 status and body. Distinguishable responses
  let anyone with the login page enumerate who has an account.
- **Verify before deciding.** On unknown email, still run an argon2 verify
  against a dummy hash. Otherwise "no such user" answers in ~1ms and "wrong
  password" in ~50ms, and the timing leaks what the response no longer does.
- **Deactivation is immediate.** `require_user` (`api/deps.py:37`) gains an
  `is_active` check, and deactivation revokes that user's sessions. Without
  both, a deactivated user keeps full access until their cookie expires —
  up to `session_ttl_days`.

The OIDC path is untouched. OIDC users keep `password_hash = NULL` and can
never authenticate through the password form.

### 5. Authorization

A factory in `api/deps.py`, layered on `require_user` so the 401 path is
unchanged and only 403 is new:

```python
def require_role(*allowed: Role):
    async def _guard(user: User = Depends(require_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(403, "insufficient role")
        return user
    return _guard
```

**Slice 1 gates exactly these routes, named explicitly** (the settings
router holds only `GET ""` and `PUT ""` — the credential-bearing routes
live in the sourcing router):

- `PUT /api/settings` (`api/settings.py:70`)
- `POST /api/sourcing/linkedin/connect` (`api/sourcing.py:183`)
- `POST /api/sourcing/linkedin/connect-cookie` (`api/sourcing.py:222`)
- `POST /api/sourcing/linkedin/disconnect` (`api/sourcing.py:259`)
- every `/api/users` route, admin-only from birth

The three LinkedIn routes are included because they accept and store
credentials — a session cookie or an email/password pair. The other
sourcing routes (`/search`, `/query/suggest`) are ordinary recruiting work
and stay open.

Everything else keeps `require_user` and behaves as today.

**Why mutation and not reads.** `SettingsRead`
(`schemas/settings.py:15`) returns `has_apify_api_key`-style booleans, never
secret values — so reads leak little. Writes are the sharp edge: any
authenticated user can currently point `local_llm_url` at a server they
control, and every CV, profile, and job description flows through it. They
can also rewrite SMTP and send mail as the organisation.

**`GET /api/settings` stays open to all active users.**
`notify-wizard.tsx` reads it for the recruiter's name and email while
drafting an invitation, so locking reads would break a normal recruiter flow
to protect data that is already just booleans and non-secret config. Slice 2
revisits whether viewers need it.

The frontend hides Settings tabs a non-admin cannot use, driven by `role` on
the existing `GET /api/auth/me` response. This is **cosmetic**; the server
check is the gate, and tests assert 403 from the API rather than trusting
the UI to hide anything.

For that, `UserRead` (`schemas/auth.py:4`) gains `role`. Note its docstring
forbids adding `sub`, `issuer`, or `last_login_at` — those are IdP
correlation keys and internal telemetry. `role` is neither: it is the
user's own authorization level, which the client must know to render its
own navigation. `is_active` is **not** added — an inactive user cannot hold
a session, so the client would never observe anything but `true`.

### 6. Admin API

All `require_role(ADMIN)`:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/users` | List: email, name, role, `is_active`, `last_login_at` |
| `POST` | `/api/users` | Create with email, name, role, initial password |
| `PATCH` | `/api/users/{id}` | Change `role` and/or `is_active` |
| `POST` | `/api/users/{id}/password` | Reset a user's password |

Plus one that is **not** admin-only:

| `POST` | `/api/auth/password` | Change your own password |

Without self-service change, the admin who created an account knows that
user's password forever.

**No `DELETE`.** Deactivation instead: `event_logs` and `auth_sessions`
reference users, so hard deletion either cascades away audit history or
fails on a foreign key.

Three guard rails, each closing a real way to break the install:

- **Never zero active admins.** Any change that would demote or deactivate
  the last active admin returns 409. Otherwise one click locks everyone out
  of user management permanently, recoverable only by hand-editing the
  database.
- **No self-deactivation** — 409 with a clearer message than the rule
  above; it is the likeliest accident.
- **Password change revokes that user's sessions.** A reset exists to cut
  off access; leaving old cookies valid defeats it.

### 7. Frontend

- **Settings → Users tab**, admin-only: table of users with inline role
  select, deactivate / reactivate, and reset-password actions, plus an Add
  User dialog (email, name, role, initial password).
- **Settings → Profile tab** gains a Change Password form, available to
  every role.
- Tabs a non-admin cannot use are hidden, based on `role` from
  `GET /api/auth/me`.

## Out of scope

Deliberately excluded from Slice 1:

- The recruiter/viewer permission matrix across all routers — **Slice 2**.
- Email invitations with tokens and expiry — **Slice 3**. Slice 1's admin
  sets an initial password and passes it along out of band; the user then
  changes it. Naming this trade-off is better than half-building an invite.
- Forced password change on first login (`must_change_password` and its
  interstitial flow).
- Per-record ownership ("my candidates"), which is a different feature from
  role tiers.
- Self-service registration and password-reset-by-email.

## Testing

Backend, stated as behaviours:

- Login returns an identical 401 for unknown email, wrong password, and
  deactivated account — three tests asserting the same status and body,
  because a difference in any is an enumeration oracle.
- Unknown email still performs a hash verification.
- Break-glass env credentials authenticate after seeding and resolve to the
  seeded admin row, not a second phantom user.
- `PUT /api/settings` returns 403 for recruiter and viewer, 200 for admin.
  Same for every `/api/users` route.
- Demoting or deactivating the last active admin returns 409;
  self-deactivation returns 409.
- Deactivating a user makes their existing cookie fail on the next request,
  not at TTL expiry.
- Password reset invalidates that user's sessions.
- The migration seeds from env, backfills existing rows to `admin`, and is
  safe to run twice.

Frontend:

- The Users tab renders only for `role === "admin"`.
- Create, deactivate, and role-change call the correct endpoints.
- The change-password form posts to `/api/auth/password`.

## Verification

- `pytest` and the frontend suite green; no new lint errors versus baseline.
- Manual: upgrade an existing deployment, confirm the current session still
  works, create a second user, log in as them, confirm they receive 403 on
  `PUT /api/settings`.
