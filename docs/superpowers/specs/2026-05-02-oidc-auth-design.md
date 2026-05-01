# OIDC SSO authentication (design)

**Status:** approved 2026-05-02
**Reopens:** the "Authentication, multi-user, SSO, RBAC — deferred to Phase 4" item from `docs/superpowers/specs/2026-04-29-recruiter-agent-design.md`.
**Closes follow-ups #20 (CSRF) + #21 (auth-gating) from Plan D.**

## Goal

Replace the current "no auth, localhost only" posture with single-tenant OIDC SSO. Recruiters at one company sign in via the company's IdP (Google Workspace, Okta, Auth0, Keycloak, anything OIDC-compliant), are auto-provisioned on first login if their email matches the configured domain allowlist, and get a server-side session backed by an HttpOnly SameSite=Strict cookie. Every API endpoint except `/health` and the `/api/auth/*` flow gets gated.

## Scope

In:
- Single-tenant, flat access (no per-org isolation, no roles).
- Generic OIDC discovery — works with any compliant IdP.
- Email-domain allowlist (single config string, comma-separated).
- Auto-provisioning on first login.
- Server-side sessions in Postgres, sliding 7-day expiry, revocable on logout.
- Cookie-based session token (HttpOnly, SameSite=Strict, Secure in prod).
- Origin header check on POST/PUT/PATCH/DELETE as belt-and-suspenders CSRF defense.
- Frontend redirect-on-401, `/me` query, logout button.
- Dev escape hatch via `RECRUITER_DEV_AUTH_BYPASS` (only active when no IdP is configured).

Out:
- RP-initiated logout (logout-of-IdP).
- Multi-IdP picker.
- RBAC / role-based gating.
- Subdomain wildcards in the allowlist.
- Active-sessions list / "sign out everywhere" UI.
- Refresh-token handling for the IdP (separate from our session).
- Account linking across IdPs.
- Admin-managed allowlist UI (env-var only in v1).

## Architecture

```
src/recruiter/
├── api/auth.py                  # /api/auth/login, /callback, /logout, /me
├── api/deps.py                  # extended: require_user() FastAPI dep
├── auth/                        # NEW package
│   ├── oidc.py                  # Authlib OIDC client: discovery, code exchange, id_token validation
│   ├── sessions.py              # create / lookup / revoke; sliding-window expiry
│   ├── allowlist.py             # exact-domain match
│   └── dev_bypass.py            # safe-by-construction dev escape hatch
├── models/user.py               # User ORM
├── models/session.py            # Session ORM
├── models/oauth_state.py        # transient PKCE/nonce state
└── schemas/auth.py              # UserRead, LoginStart, etc.

recruiter-frontend/src/
├── hooks/use-current-user.ts    # /me query
├── lib/api.ts                   # extended: 401 → redirect to /api/auth/login
├── components/layout/app-shell.tsx  # user chip + logout
└── components/auth/             # NEW: not-authorized page (403 from /callback)
```

Library: **Authlib** (`Authlib>=1.3`), via `authlib.integrations.httpx_client`. Handles `.well-known/openid-configuration` discovery, PKCE code_challenge/verifier, id_token signature + claim validation in ~20 lines of glue.

The flow is redirect-based, not popup or SPA-managed. The browser owns the redirect; the backend sets the cookie on the final 302.

```
Browser                          Backend                              IdP
  ─── GET /api/jobs ──────────►
  ◄───── 401 ─────────────────┘
  ─── /api/auth/login?next=/jobs ──►
                                    ─── 302 to {issuer}/authorize?
                                                state=<random>&
                                                nonce=<random>&
                                                code_challenge=<S256>&
                                                redirect_uri=<our_callback>&
                                                scope=openid email profile&
                                                hd=<domain> ──────────►
  ◄────── 302 redirect ──────────┘                                     │
  ─── follows redirect ──────────────────────────────────────────────►
                                                              (user authenticates)
  ◄────── 302 to /api/auth/callback?code=…&state=… ────────────────────┘
  ─── follows ───────────────────►
                                    ─── POST {token_endpoint} ──────────►
                                    ◄─── id_token + access_token ──────┘
                                  validates id_token (sig, iss, aud, exp,
                                                      nonce, email_verified)
                                  checks email domain ∈ allowed_domains
                                  upserts users (by sub, issuer)
                                  creates sessions row
                                  sets recruiter_session cookie
  ◄──── 302 to /jobs (cookie set) ─┘
  ─── GET /api/jobs (with cookie) ─►
  ◄──── 200 ─────────────────────┘
```

## Data model

Three new tables.

### `users`

```python
class User(Base):
    __tablename__ = "users"

    id:              Mapped[int]                     # pk
    email:           Mapped[str]                     # unique, indexed
    sub:             Mapped[str | None]              # OIDC subject claim
    issuer:          Mapped[str | None]              # OIDC issuer URL (for sub-by-issuer uniqueness)
    name:            Mapped[str | None]              # from id_token "name"
    picture:         Mapped[str | None]              # avatar URL, optional
    last_login_at:   Mapped[datetime | None]
    created_at, updated_at
```

Lookup on first login matches `(issuer, sub)`; thereafter `email` updates if it changes upstream. Unique on `email` (single tenant), and a separate unique index on `(issuer, sub)`.

### `sessions`

```python
class Session(Base):
    __tablename__ = "sessions"

    id:           Mapped[str]                       # pk — 32-byte URL-safe random; stored in cookie
    user_id:      Mapped[int]                       # fk users.id ondelete=CASCADE, indexed
    expires_at:   Mapped[datetime]                  # sliding 7-day window
    created_at:   Mapped[datetime]
    last_seen_at: Mapped[datetime]                  # bumped at most once per hour
    user_agent:   Mapped[str | None]                # opt-in audit
    ip:           Mapped[str | None]                # opt-in audit
```

Composite index `(id, expires_at)` so the lookup-and-validate is one query. `user_id` indexed for revoke-all-sessions-for-user (deferred but the index is cheap).

### `oauth_states`

```python
class OAuthState(Base):
    __tablename__ = "oauth_states"

    state:          Mapped[str]                     # pk — random, sent to IdP, returned in callback
    nonce:          Mapped[str]                     # id_token nonce check
    pkce_verifier:  Mapped[str]                     # PKCE code_verifier
    next_url:       Mapped[str]                     # post-login redirect target
    created_at:     Mapped[datetime]                # rows older than 10 min reaped on lookup
```

Single Alembic migration creates all three tables.

## OIDC flow

### `GET /api/auth/login?next=<path>`

1. Generate `state`, `nonce`, `pkce_verifier` (random URL-safe), compute `code_challenge = base64url(sha256(verifier))`.
2. Insert `oauth_states` row.
3. Build authorize URL from issuer's discovery doc:
   `{authorization_endpoint}?response_type=code&client_id=<cid>&redirect_uri=<our_callback>&scope=openid email profile&state=<state>&nonce=<nonce>&code_challenge=<challenge>&code_challenge_method=S256`.
   For Google Workspace, append `&hd=<domain>` (server-side enforcement, defense in depth alongside our domain allowlist).
4. `302` to that URL.

### `GET /api/auth/callback?code=...&state=...`

1. Look up `state` in `oauth_states`. If missing or older than 10 min → `400`. Delete the row regardless on success/failure.
2. POST to `{token_endpoint}` with `code`, `client_id`, `client_secret`, `redirect_uri`, `code_verifier`. Get back `id_token` + `access_token`.
3. Validate `id_token` via Authlib: signature against IdP JWKS, `iss == config.issuer`, `aud == client_id`, `exp` not past, `nonce` matches stored. Fail → `400`.
4. Read claims: `sub`, `email`, `email_verified`, `name`, `picture`.
5. If `email_verified` is explicitly `False`: reject (`403`). If absent: treat as verified (Google omits it sometimes; documented above).
6. If `email`'s domain not in `allowed_domains`: `403` rendering the not-authorized page.
7. Upsert `users` by `(issuer, sub)`: update `email`, `name`, `picture`, `last_login_at`. Insert if new.
8. Create `sessions` row: `id = secrets.token_urlsafe(32)`, `expires_at = now + 7 days`.
9. Delete the consumed `oauth_states` row.
10. Set cookie:
    `Set-Cookie: recruiter_session=<id>; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800` (+ `Secure` if `Config.secure_cookies`).
11. `302` to `next_url`.

### `POST /api/auth/logout`

1. Resolve session via cookie. If missing → `204` (idempotent).
2. Delete the `sessions` row.
3. Set cookie with `Max-Age=0`.
4. `204`.

### `GET /api/auth/me`

1. `require_user` dep.
2. Return `UserRead = {id, email, name, picture}`.
3. No session → `401`. Frontend uses this signal on initial mount.

## Session lifecycle and gating

### `require_user` FastAPI dep

```python
async def require_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    # Dev escape hatch: only when no IdP is configured AND bypass is set.
    user = await dev_bypass.maybe_resolve(session)
    if user is not None:
        return user

    cookie = request.cookies.get("recruiter_session")
    if not cookie:
        raise HTTPException(status_code=401, detail="not authenticated")

    row = (await session.execute(
        select(Session)
        .where(Session.id == cookie)
        .where(Session.expires_at > func.now())
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=401, detail="session expired")

    # Sliding window: bump last_seen_at + extend expires_at, but only if the
    # bump is meaningful (>=1h since last) to avoid hot-write contention.
    now = datetime.now(tz=timezone.utc)
    if (now - row.last_seen_at) > timedelta(hours=1):
        row.last_seen_at = now
        row.expires_at = now + timedelta(days=7)
        await session.commit()

    user = await session.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="user not found")
    return user
```

### Origin check

Middleware on POST/PUT/PATCH/DELETE: if the `Origin` header is present and not in `Config.allowed_origins`, respond `403`. SameSite=Strict already blocks the cross-site cookie; the Origin check is belt-and-suspenders against legacy browsers and same-site-but-different-port footguns.

### Endpoints gated by `require_user`

All of `/api/jobs/*`, `/api/applications/*`, `/api/candidates/*`, `/api/notifications/*`, `/api/settings/*`, `/api/events`.

### Endpoints NOT gated

`/health`, `/api/auth/login`, `/api/auth/callback`, `/api/auth/me`, `/api/auth/logout`. That's it.

### Cookie flags

| Flag | Value | Why |
|---|---|---|
| `HttpOnly` | yes | XSS can't read the token. |
| `SameSite` | `Strict` | CSRF mitigation; cross-site requests don't include it. |
| `Secure` | `Config.secure_cookies` | Off for localhost dev (HTTP); on for prod (HTTPS). |
| `Path` | `/` | All routes. |
| `Max-Age` | `604800` (7 days) | Refreshed by the sliding-window bump. |

## Frontend integration

### `lib/api.ts` — 401 handling

```ts
// extending existing api()
if (response.status === 401) {
  const next = encodeURIComponent(window.location.pathname + window.location.search);
  window.location.href = `${BASE_URL}/api/auth/login?next=${next}`;
  throw new ApiError(401, "redirecting to login");
}
```

Plus add `credentials: "include"` to the fetch call so cookies flow cross-origin in dev.

### `hooks/use-current-user.ts`

```ts
export function useCurrentUser() {
  return useQuery({
    queryKey: queryKeys.currentUser(),
    queryFn: () => api<UserRead>("/api/auth/me"),
    retry: false,
  });
}
```

### `AppShell` header

User chip on the right showing `email` from `useCurrentUser()`, with a dropdown containing "Sign out". Clicking Sign out: `POST /api/auth/logout`, then `qc.invalidateQueries({ queryKey: queryKeys.currentUser() })`, then reload to `/`.

### Auth callback

The OIDC callback is a **backend** endpoint (`/api/auth/callback`). The backend handles the IdP redirect and ends with a `302` back to a frontend route (`next_url`, default `/`). No frontend route needed.

### Not-authorized page

When the backend `/callback` returns `403` (email not in allowlist), it renders a small static HTML page server-side: "Your account isn't authorized for this deployment. Contact your admin." rather than redirecting back to the frontend. Avoids a redirect loop.

## Deployment + dev ergonomics

### Local dev env vars

```
RECRUITER_OIDC_ISSUER=https://accounts.google.com
RECRUITER_OIDC_CLIENT_ID=<from Google Cloud Console>
RECRUITER_OIDC_CLIENT_SECRET=<from Google Cloud Console>
RECRUITER_OIDC_REDIRECT_URI=http://localhost:8765/api/auth/callback
RECRUITER_OIDC_ALLOWED_DOMAINS=acme.com
RECRUITER_SECURE_COOKIES=false
```

### Dev escape hatch — `RECRUITER_DEV_AUTH_BYPASS`

When set AND `RECRUITER_OIDC_ISSUER` is empty, `require_user` auto-resolves to a synthetic user with the bypass email. This keeps the test suite functional without spinning up an IdP and lets contributors run the app offline.

**Safe by construction:** the bypass only activates when no IdP is configured. A misconfigured prod that sets `RECRUITER_DEV_AUTH_BYPASS` but ALSO has `RECRUITER_OIDC_ISSUER` will fall through to OIDC — which is the right failure mode.

### CORS and credentials

`main.py` flips `allow_credentials=False → True`. `allow_origins` stays the existing restrictive list. Frontend `fetch` calls add `credentials: "include"`.

### Google Cloud Console one-time setup

- Create OAuth 2.0 Client ID (Web application).
- Authorized redirect URI: `http://localhost:8765/api/auth/callback` (dev), `https://recruiter.acme.com/api/auth/callback` (prod).
- Authorized JavaScript origins: `http://localhost:5173` (dev), `https://recruiter.acme.com` (prod).
- For Workspace-only domain restriction, the authorize URL adds `hd=<domain>`.

### Prod posture

- `RECRUITER_SECURE_COOKIES=true` — HTTPS-only.
- Origin check middleware enabled.
- `RECRUITER_DEV_AUTH_BYPASS` MUST NOT be set.
- IdP redirect URI updated to prod hostname.

## Testing strategy

### Backend unit (pytest)

- `auth/oidc.py::OIDCClient` — `httpx.MockTransport` for `.well-known/openid-configuration` and `/token`; PKCE round-trip; state and nonce propagate; malformed token responses raise.
- `auth/sessions.py` — `create_session`, `lookup_session`, `revoke`, sliding expiry.
- `auth/allowlist.py::is_email_allowed("alice@acme.com", ["acme.com"])` — exact-domain match (no subdomain wildcards in v1).
- `models/user.py`, `models/session.py`, `models/oauth_state.py` — round-trip tests with `db_session_with_schema`.

### Backend API (pytest + httpx ASGITransport)

- `GET /api/auth/login?next=/jobs` → 302 to `accounts.example.com/authorize?...`; `oauth_states` row created with `next_url=/jobs`.
- `GET /api/auth/callback?code=…&state=<known>` — mock IdP `/token` to return a fake id_token signed with a test key, mock JWKS endpoint. Assert: user upserted, session created, `Set-Cookie` present, 302 to `next_url`.
- `GET /api/auth/callback?code=…&state=unknown` → 400.
- `GET /api/auth/callback` with id_token whose email is not in `allowed_domains` → 403.
- `GET /api/auth/me` no cookie → 401.
- `GET /api/auth/me` valid cookie → 200, payload.
- `POST /api/auth/logout` valid cookie → 204; subsequent `/me` → 401; sessions row deleted.
- Sliding window: active session whose `last_seen_at` is 2h ago → next request bumps `expires_at`. Same session 5 minutes later → no DB write (idle-bump throttled).

### Backend gating sweep

One parametrized test that hits each gated endpoint without a cookie and asserts 401. Catches any future endpoint that forgets to depend on `require_user`.

### Test refactor (largest non-feature impact)

Every existing API test needs to use a new `api_client_authed` fixture that creates a user + session and attaches the cookie. Today there are ~50 backend API tests that hit gated endpoints unauthenticated; they all need this. Mechanical but wide.

### Frontend (Vitest + RTL + MSW)

- `useCurrentUser` — 200 → query has data; 401 → query errored, no infinite-retry.
- `lib/api.ts` 401 redirect — mock `window.location.href` setter, assert it gets the right URL.
- `AppShell` user chip — query data renders email; logout fires `POST /logout` and reloads.

### Manual smoke (real Google Workspace, added to SMOKE.md)

1. With dev backend + frontend running and `RECRUITER_OIDC_*` configured: open `/`, get redirected to Google's consent screen, sign in, land back on `/jobs` authenticated.
2. Settings → Sign out → return to `/` with login redirect on next request.
3. Try a non-allowlisted Google account → not-authorized page.
4. Wait 7+ days idle (or temp-set the TTL low), verify re-auth required.

### Out of scope for tests

- IdP-side auth UX (we trust Authlib's id_token validation).
- RP-initiated logout, multi-IdP, refresh-token rotation, MFA enforcement.

## Error handling

- **State mismatch** (callback with unknown state) — `400` "invalid login session, please try again". User restarts at `/api/auth/login`.
- **Expired state** (>10 min between login start and callback) — same as above, `400`.
- **Token endpoint 5xx** — `502` "auth provider unavailable, retry"; logs the upstream response.
- **id_token validation failure** — `400`. Log full claims to server logs.
- **Email not verified or domain not allowed** — `403` rendering the not-authorized page.
- **Database failure during user upsert** — `500`; the consumed `oauth_states` row is restorable from the IdP's resent code only on retry, so the user just sees an error and clicks again.
- **Logout when not logged in** — `204` (idempotent).
- **Frontend 401** — auto-redirect to `/api/auth/login?next=<current>`. The redirect bypasses the normal `ApiError` toast.

## Open questions

Items deferred or to be confirmed during implementation:

- **Authlib version + flavor.** Commit to `Authlib>=1.3` and `authlib.integrations.httpx_client`. Verify exact API surface during impl.
- **`Config.secure_cookies` default.** `False` (so localhost dev works over HTTP); production deploys must set `RECRUITER_SECURE_COOKIES=true` explicitly.
- **`oauth_states` reaping.** Stale rows swept on lookup (cheap). If volume ever surfaces wasted storage, add a periodic delete.
- **Email-verified missing claim.** Treat absent as verified (Google omits it sometimes). Can tighten later if a non-Google IdP is added.
- **Account migration when a user's email changes upstream.** Match by `(issuer, sub)`, update the email column. If two users somehow share an email but different `sub` (provider migration edge case), the unique constraint on `email` causes the second login to fail. Documented; not handled.

## Implementation phasing

Suggested order for the writing-plans pass:

1. `models/user.py`, `models/session.py`, `models/oauth_state.py` + Alembic migration.
2. `auth/oidc.py` — discovery + token exchange + id_token validation, with `httpx.MockTransport` tests.
3. `auth/sessions.py` — create/lookup/revoke + sliding window.
4. `auth/allowlist.py` + `auth/dev_bypass.py`.
5. `api/auth.py` — login, callback, logout, me endpoints.
6. `api/deps.py::require_user` + Origin-check middleware.
7. **Test refactor:** new `api_client_authed` fixture; update all ~50 existing API tests.
8. Gate every gated endpoint with `Depends(require_user)`. Run the gating-sweep parametrized test.
9. Frontend: `lib/api.ts` 401 redirect, `useCurrentUser`, AppShell user chip, logout button.
10. Docs: README "Auth setup" section, SMOKE.md update.
11. Manual smoke against real Google Workspace.
