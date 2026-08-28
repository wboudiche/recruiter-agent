# Viewer Permission Matrix (Slice 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `viewer` role genuinely read-only, without taking away the chat that makes a viewer account worth having.

**Architecture:** One app-level dependency denies every mutating method to viewers unless the route template is on a short allowlist, so routes added later are closed by default. Chat is allowlisted and constrained inside the agent instead: the tool list is filtered by role, and the three write executors re-check independently.

**Tech Stack:** FastAPI + SQLAlchemy 2 (async) on the backend; React 18 + TanStack Query + Vitest on the frontend.

## Global Constraints

- Python line length ≤ 100 chars (ruff `E501`). Match existing style; do not reformat untouched lines.
- Run every command from the repo root `/home/walidboudiche/recruiter-agent`.
- Backend tests: `.venv/bin/python -m pytest`. Frontend: `npm test --prefix recruiter-frontend`. Types: `npm run --prefix recruiter-frontend lint` (this is `tsc --noEmit`; there is **no** `typecheck` script).
- Ruff bar: no NEW error categories in touched files versus baseline. FastAPI's `Depends(...)` default triggers `B008` throughout this repo already; another instance of that idiom is acceptable.
- `require_user`'s behaviour must not change for existing callers — same 401s, same `is_active` check, same sliding-window touch.
- Viewer refusals return **403** with detail `"read-only role"`, distinct from the 401 of an expired session.
- Do not add read-gating: viewers keep `GET` access to everything they can see today.
- Commit after each task. Branch is `feat/viewer-permission-matrix`.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/recruiter/api/deps.py` | Split `maybe_user` out of `require_user`; add the guard | Modify |
| `src/recruiter/api/permissions.py` | The allowlist and the mutating-method set — one place to read the policy | Create |
| `src/recruiter/main.py` | Register the guard app-wide | Modify |
| `src/recruiter/agent/tools.py` | `ToolContext.role`; `tools_for(role)`; executor re-checks | Modify |
| `src/recruiter/agent/chat.py:76` | Thread `role` into `run_turn` and the context | Modify |
| `src/recruiter/api/chat.py:43` | Pass the caller's role to `run_turn` | Modify |
| `tests/api/test_viewer_matrix.py` | Route-level enforcement, incl. the fail-closed property | Create |
| `tests/unit/test_agent_tool_permissions.py` | Tool filtering + executor re-checks | Create |
| `recruiter-frontend/src/hooks/use-current-user.ts` | Expose `canWrite` | Modify |
| `recruiter-frontend/src/components/kanban/*`, `routes/job-detail.tsx` | Hide write controls | Modify |

---

### Task 1: `maybe_user` and the read-only guard

**Files:**
- Create: `src/recruiter/api/permissions.py`
- Modify: `src/recruiter/api/deps.py` (split `require_user`, add guard), `src/recruiter/main.py`
- Test: `tests/api/test_viewer_matrix.py` (create)

**Interfaces:**
- Consumes: `Role`, `User` from `recruiter.models`; existing `require_user` behaviour.
- Produces:
  - `maybe_user(request, session) -> User | None` — resolves dev bypass then session cookie, **never raises**
  - `require_user(...)` — unchanged behaviour, now built on `maybe_user`
  - `MUTATING_METHODS: frozenset[str]` and `VIEWER_ALLOWED_ROUTES: frozenset[tuple[str, str]]` in `permissions.py`
  - `viewer_readonly_guard(request, user)` — app-level dependency raising 403 `"read-only role"`

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_viewer_matrix.py`:

```python
"""A viewer must be read-only, and must STAY read-only as routes are added.

Enforcement is default-deny: any mutating method is refused unless the
route template is explicitly allowlisted. The fail-closed test below is
the property the whole design exists for — if it is ever deleted as
"weird", a future route silently ships open to viewers.
"""

import pytest
from fastapi import Depends, FastAPI
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
    is gone and nothing else would notice."""
    from recruiter.api.deps import get_session

    probe = FastAPI(dependencies=[Depends(viewer_readonly_guard)])

    @probe.post("/api/invented/tomorrow")
    async def invented() -> dict:
        return {"reached": True}

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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/api/test_viewer_matrix.py -v`
Expected: FAIL at import — `cannot import name 'viewer_readonly_guard'` and `No module named 'recruiter.api.permissions'`.

- [ ] **Step 3: Write the policy module**

Create `src/recruiter/api/permissions.py`:

```python
"""Who may do what — the viewer read-only policy, in one place.

Default-deny by design: a viewer is refused every mutating method unless
the route template appears below. A route added later is therefore closed
to viewers until someone opts it in deliberately, rather than silently
shipping open. That trade is the point — the surprise moves from
"shipped open" to "shipped closed", which is the direction worth having.
"""

MUTATING_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})

# (method, route TEMPLATE) — templates, not concrete paths, so ids in
# URLs never have to be matched with a regex.
VIEWER_ALLOWED_ROUTES = frozenset({
    # Chat is the reason a viewer account is worth having: a hiring
    # manager can interrogate a shortlist. Safe here only because the
    # agent withholds its write tools from viewers (see agent/tools.py);
    # allowlisting this route WITHOUT that filter would let a viewer
    # validate and reject candidates by conversation.
    ("POST", "/api/applications/{application_id}/chat"),
    # Every role changes its own password.
    ("POST", "/api/auth/password"),
    # Refusing logout would be absurd.
    ("POST", "/api/auth/logout"),
    # Anonymous anyway — the guard never sees a user here. Listed so a
    # future refactor that authenticates earlier cannot break login.
    ("POST", "/api/auth/login/password"),
})
```

- [ ] **Step 4: Split `maybe_user` out of `require_user`**

In `src/recruiter/api/deps.py`, replace the body of `require_user` with a
`maybe_user` that never raises, plus a thin `require_user` on top:

```python
async def maybe_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User | None:
    """Resolve the logged-in User, or None. NEVER raises.

    Split out of `require_user` so the app-level read-only guard can ask
    "who is this?" without forcing authentication — the guard runs on
    every route including public ones, and a raising resolver there would
    401 the login page.

    FastAPI caches dependencies per request, so a route that also depends
    on `require_user` resolves this once, not twice: no extra session
    lookup is introduced by the guard.
    """
    bypass_user = await dev_bypass.maybe_resolve(session)
    if bypass_user is not None:
        return bypass_user if bypass_user.is_active else None

    cookie = request.cookies.get("recruiter_session")
    if not cookie:
        return None
    user = await lookup_session(session, token=cookie)
    if user is None or not user.is_active:
        return None

    cfg = get_config()
    # Sliding-window bump is best-effort: a transient DB hiccup must not
    # 500 an otherwise-authenticated user. Throttled to once/hour anyway.
    try:
        await touch_session(session, token=cookie, ttl_days=cfg.session_ttl_days)
    except Exception:
        logger.warning("touch_session failed; continuing without bump", exc_info=True)
    return user


async def require_user(user: User | None = Depends(maybe_user)) -> User:
    """Resolve the logged-in User or raise 401. Mounts on every gated route."""
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user
```

Note the deliberate loss of detail: the old code distinguished
`"not authenticated"` from `"session expired"`. Both now return
`"not authenticated"`. That is acceptable — the distinction told an
unauthenticated caller whether a cookie had once been valid, which is
information they do not need, and the frontend keys on the 401 status.

- [ ] **Step 5: Add the guard**

At the end of `src/recruiter/api/deps.py`:

```python
def _route_template(request: Request) -> str | None:
    """The matched route's template, e.g. /api/applications/{id}/chat.

    App-level dependencies run AFTER routing, so the resolved route is on
    the scope. Matching the template rather than the concrete path means
    ids embedded in URLs never need a regex.
    """
    route = request.scope.get("route")
    return getattr(route, "path", None)


async def viewer_readonly_guard(
    request: Request,
    user: User | None = Depends(maybe_user),
) -> None:
    """Refuse mutations to viewers unless the route is allowlisted.

    Registered app-wide, so a router that does not exist yet is covered
    the day it is added. Anonymous callers pass straight through: this
    enforces role, not authentication, and the route's own dependencies
    still return 401 where they should.
    """
    if user is None or user.role != Role.VIEWER:
        return
    if request.method not in MUTATING_METHODS:
        return
    template = _route_template(request)
    if template and (request.method, template) in VIEWER_ALLOWED_ROUTES:
        return
    raise HTTPException(status_code=403, detail="read-only role")
```

Add the import: `from recruiter.api.permissions import MUTATING_METHODS, VIEWER_ALLOWED_ROUTES`.

- [ ] **Step 6: Register the guard app-wide**

In `src/recruiter/main.py`, change the app construction:

```python
app = FastAPI(
    title="Recruiter Agent",
    lifespan=lifespan,
    # App-level, so routers added later are covered without anyone
    # remembering to opt in. See api/permissions.py for the policy.
    dependencies=[Depends(viewer_readonly_guard)],
)
```

Add imports: `from fastapi import Depends, FastAPI` (extend the existing
FastAPI import) and `from recruiter.api.deps import viewer_readonly_guard`.

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/api/test_viewer_matrix.py -v`
Expected: PASS, 6 tests.

If `test_viewer_is_refused_every_non_allowlisted_mutation` reports routes
that got through, read each one before adding it anywhere: a genuine miss
means the guard is wrong, not that the route deserves allowlisting.

- [ ] **Step 8: Run the full backend suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass. Existing tests use the dev-bypass user (`Role.ADMIN`),
so the guard is inert for them.

- [ ] **Step 9: Commit**

```bash
git add src/recruiter/api/permissions.py src/recruiter/api/deps.py \
        src/recruiter/main.py tests/api/test_viewer_matrix.py
git commit -m "feat(auth): default-deny mutations for the viewer role"
```

---

### Task 2: Withhold the agent's write tools from viewers

**Files:**
- Modify: `src/recruiter/agent/tools.py` (`ToolContext` at :20, `TOOLS` at :222/:358, the three write handlers)
- Modify: `src/recruiter/agent/chat.py:76` (`run_turn`), `src/recruiter/api/chat.py:43` (`post_chat`)
- Test: `tests/unit/test_agent_tool_permissions.py` (create)

**Interfaces:**
- Consumes: `Role` from `recruiter.models`; `VIEWER_ALLOWED_ROUTES` from Task 1 (chat is allowlisted, which is *why* this task exists).
- Produces:
  - `ToolContext.role: Role` (new field)
  - `tools_for(role: Role) -> list[ToolDef]`
  - `WRITE_TOOL_NAMES: frozenset[str]` = `{"save_note", "validate_application", "reject_application"}`
  - `run_turn(..., role: Role)` — new required keyword argument

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_agent_tool_permissions.py`:

```python
"""Chat is allowlisted for viewers, so the write capability has to be
removed inside the agent.

`POST /applications/{id}/chat` looks conversational but carries three
mutating tools. A viewer reaching chat with those tools available could
validate and reject candidates by conversation, while
`PATCH /applications/{id}` is gated shut — a hole exactly as wide as the
route-level gate it bypasses.
"""

import pytest

from recruiter.agent.tools import (
    WRITE_TOOL_NAMES, ToolContext, get_tool_handler, tools_for,
)
from recruiter.models import Role


def test_viewer_is_offered_no_write_tools() -> None:
    names = {t.name for t in tools_for(Role.VIEWER)}

    assert names & WRITE_TOOL_NAMES == set()


def test_viewer_keeps_the_read_and_search_tools() -> None:
    """Withholding writes must not gut the feature: answering "why did
    this candidate score low?" is the reason viewers get chat at all."""
    names = {t.name for t in tools_for(Role.VIEWER)}

    assert {"get_candidate", "get_application", "get_score_breakdown"} <= names
    assert "search_web" in names


@pytest.mark.parametrize("role", [Role.RECRUITER, Role.ADMIN])
def test_recruiters_and_admins_keep_every_tool(role: Role) -> None:
    names = {t.name for t in tools_for(role)}

    assert WRITE_TOOL_NAMES <= names


@pytest.mark.parametrize("tool_name", sorted(WRITE_TOOL_NAMES))
@pytest.mark.asyncio
async def test_write_handlers_refuse_a_viewer_even_if_called_directly(
    tool_name: str, db_session_with_schema, monkeypatch,
) -> None:
    """The second layer, deliberately redundant. If a later refactor
    rebuilds the tool list and forgets the filter, the mutation must still
    not happen."""
    ctx = ToolContext(
        session=db_session_with_schema,
        application_id=1,
        undo_store={},
        role=Role.VIEWER,
    )
    handler = get_tool_handler(tool_name)

    with pytest.raises(PermissionError):
        await handler(ctx, {"text": "x", "reason": "x", "notes": "x"})
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_agent_tool_permissions.py -v`
Expected: FAIL at import — `cannot import name 'tools_for'`.

- [ ] **Step 3: Add the role to `ToolContext`**

In `src/recruiter/agent/tools.py`, add to the `ToolContext` dataclass (:20):

```python
    # The caller's authorization level. `role`, not the whole User: the
    # handlers need an authorization decision, not an identity, and a
    # narrower field is harder to misuse later for something else.
    role: Role = Role.RECRUITER
```

Import `Role` from `recruiter.models`. The default keeps every existing
construction working; the chat path sets it explicitly in Step 6.

- [ ] **Step 4: Add `WRITE_TOOL_NAMES` and `tools_for`**

At the end of `src/recruiter/agent/tools.py`, after the `TOOLS.extend([...])` block:

```python
# The tools that change state. Named once, so the tool list filter and
# the handler re-checks below cannot drift apart.
WRITE_TOOL_NAMES = frozenset({"save_note", "validate_application", "reject_application"})


def tools_for(role: Role) -> list[ToolDef]:
    """The tools a caller of this role may use.

    A model cannot call a tool it was never given, so withholding here is
    a real boundary rather than a prompt instruction asking it not to.
    """
    if role == Role.VIEWER:
        return [t for t in TOOLS if t.name not in WRITE_TOOL_NAMES]
    return list(TOOLS)
```

- [ ] **Step 5: Make the write handlers re-check**

In `src/recruiter/agent/tools.py`, at the top of each of the three write
handlers (the functions registered as `save_note`,
`validate_application`, `reject_application`), add:

```python
    if ctx.role == Role.VIEWER:
        # Unreachable while `tools_for` filters correctly — which is the
        # point. This survives a refactor that rebuilds the tool list and
        # forgets the filter.
        raise PermissionError("read-only role cannot modify applications")
```

- [ ] **Step 6: Thread the role through chat**

In `src/recruiter/agent/chat.py`, add a required keyword to `run_turn` (:76):

```python
async def run_turn(
    *,
    session: AsyncSession,
    application_id: int,
    user_message: str,
    llm: LLMClient,
    undo_store: UndoStore,
    role: Role,
    max_steps: int = MAX_STEPS_DEFAULT,
) -> AsyncIterator[dict]:
```

Set it on the context (:111) and use the filtered list at the LLM call (:121):

```python
    ctx = ToolContext(
        session=session, application_id=application_id,
        undo_store=undo_store, role=role,
    )
```

```python
                history, tools_for(role), system=system,
```

Import `Role` from `recruiter.models` and `tools_for` from
`recruiter.agent.tools` (replacing the `TOOLS` import).

In `src/recruiter/api/chat.py`, `post_chat` (:43) currently has no user
dependency. Add one and pass the role through:

```python
    user: User = Depends(require_user),
```

```python
                async for event in run_turn(
                    session=own_session,
                    application_id=application_id,
                    user_message=payload.message,
                    llm=llm,
                    undo_store=undo_store,
                    role=user.role,
                ):
```

Add imports: `require_user` from `recruiter.api.deps` and `User` from
`recruiter.models`.

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/unit/test_agent_tool_permissions.py -v`
Expected: PASS, 8 tests (3 + 2 parametrised + 3 parametrised).

- [ ] **Step 8: Run the full backend suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass. If a chat test fails on the new required `role`
argument, pass `role=Role.RECRUITER` at that call site — do not give
`run_turn` a default, because a missing role there should be a loud
error, not a silent grant.

- [ ] **Step 9: Commit**

```bash
git add src/recruiter/agent/tools.py src/recruiter/agent/chat.py \
        src/recruiter/api/chat.py tests/unit/test_agent_tool_permissions.py
git commit -m "feat(agent): withhold write tools from viewers, in two layers"
```

---

### Task 3: Hide write controls from viewers

**Files:**
- Modify: `recruiter-frontend/src/hooks/use-current-user.ts`
- Modify: `recruiter-frontend/src/components/kanban/candidate-card.tsx`, `kanban-column.tsx`, `kanban-board.tsx`, `add-candidate-panel.tsx` usage in `routes/job-detail.tsx`
- Test: `recruiter-frontend/src/routes/job-detail.test.tsx` (create or extend)

**Interfaces:**
- Consumes: `role` on `GET /api/auth/me` (already present from Slice 1).
- Produces: `useCanWrite(): boolean` in `use-current-user.ts`.

- [ ] **Step 1: Write the failing test**

Create `recruiter-frontend/src/routes/job-detail.test.tsx` (if it exists, add these cases to it):

```tsx
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import JobDetail from "./job-detail";

const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: apiMock };
});

function mockApiForRole(role: "admin" | "recruiter" | "viewer") {
  apiMock.mockReset();
  apiMock.mockImplementation((path: string) => {
    if (path === "/api/auth/me") {
      return Promise.resolve({ id: 1, email: "u@acme.com", name: null, picture: null, role });
    }
    if (path.startsWith("/api/jobs/8/applications")) return Promise.resolve([]);
    if (path.startsWith("/api/jobs/8")) {
      return Promise.resolve({ id: 8, title: "Senior Data Scientist", description: "d", criteria: [], status: "open" });
    }
    return Promise.resolve([]);
  });
}

function renderJob() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/jobs/8"]}>
        <Routes>
          <Route path="/jobs/:jobId" element={<JobDetail />} />
        </Routes>
      </QueryClientProvider>,
    );
}

beforeEach(() => mockApiForRole("recruiter"));

describe("JobDetail write controls", () => {
  it("offers Add candidate to a recruiter", async () => {
    mockApiForRole("recruiter");
    renderJob();

    expect(await screen.findByRole("button", { name: /add candidate/i })).toBeInTheDocument();
  });

  it("hides Add candidate from a viewer", async () => {
    mockApiForRole("viewer");
    renderJob();

    // Wait for the board to settle so this is not just an early render.
    await screen.findByText(/senior data scientist/i);
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /add candidate/i })).not.toBeInTheDocument(),
    );
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm test --prefix recruiter-frontend -- job-detail`
Expected: FAIL — the viewer case still finds the Add candidate button.

- [ ] **Step 3: Expose `useCanWrite`**

In `recruiter-frontend/src/hooks/use-current-user.ts`, add below the existing hook:

```ts
/** False for viewers. Cosmetic only — the server's 403s are the real
 *  gate; this exists so a viewer is not shown buttons that cannot work. */
export function useCanWrite(): boolean {
  const me = useCurrentUser();
  return me.data ? me.data.role !== "viewer" : false;
}
```

Defaulting to `false` while loading means a viewer never sees a flash of
controls they cannot use; a recruiter sees them a moment later.

- [ ] **Step 4: Hide the controls**

In `recruiter-frontend/src/routes/job-detail.tsx`, call `useCanWrite()` and
wrap the **Add candidate** trigger in `{canWrite && ...}`.

In `recruiter-frontend/src/components/kanban/candidate-card.tsx`, take a
`canWrite?: boolean` prop (default `true`) and use it in two places:

```tsx
  const isDraggable = draggable && canWrite && application.stage !== "extracting";
```

and gate the Retry button, which already renders conditionally, on
`canWrite && canRetry`.

Thread `canWrite` from `job-detail.tsx` → `kanban-board.tsx` →
`kanban-column.tsx` → `candidate-card.tsx`, exactly as `jobId` is
threaded today.

In `recruiter-frontend/src/routes/application-detail.tsx`, the write
controls are not inline — they live in two child components. Gate both:

```tsx
  const canWrite = useCanWrite();
```

`<ActionBar ... />` at line 70 holds Validate, Reject and Notify
(`components/candidate/action-bar.tsx:43` is the Notify trigger):

```tsx
            {canWrite && (
              <ActionBar
                {/* keep the existing props exactly as they are */}
              />
            )}
```

`<PasteProfileForm ... />` at line 100 submits a profile, which creates
data, so it is a write too:

```tsx
          {canWrite && (
            <PasteProfileForm
              {/* keep the existing props exactly as they are */}
            />
          )}
```

Leave `ChatPanel` (line 111) visible — chat is allowlisted for viewers,
and hiding it here would remove the one thing this whole slice went out
of its way to preserve.

- [ ] **Step 5: Add the read-only explanation**

In `recruiter-frontend/src/routes/job-detail.tsx`, next to the toolbar:

```tsx
      {!canWrite && (
        <p className="text-xs text-muted-foreground">
          Read-only access — ask an admin for a recruiter account to add or move candidates.
        </p>
      )}
```

Without it, an empty toolbar reads as a broken page rather than a
permission boundary.

- [ ] **Step 6: Run the frontend suite and typecheck**

Run: `npm test --prefix recruiter-frontend && npm run --prefix recruiter-frontend lint`
Expected: all tests pass, no TypeScript errors.

- [ ] **Step 7: Commit**

```bash
git add recruiter-frontend/src
git commit -m "feat(kanban): hide write controls from viewers"
```

---

### Task 4: Verify against the running stack

**Files:** none — manual verification.

**Interfaces:** consumes everything from Tasks 1-3.

- [ ] **Step 1: Rebuild and restart**

```bash
docker compose build backend frontend && docker compose up -d --force-recreate
until [ "$(docker inspect -f '{{.State.Health.Status}}' recruiter-agent-backend-1)" = "healthy" ]; do sleep 5; done
```

- [ ] **Step 2: Create a viewer**

In Settings → Users (as admin), add `viewer.test@acme.com` with role
**Viewer** and password `viewer-pw-123`.

- [ ] **Step 3: Check the API boundary directly**

```bash
J=/tmp/viewer.txt; rm -f $J
curl -s -o /dev/null -w "login: %{http_code}\n" -c $J -X POST http://localhost:8088/api/auth/login/password \
  -H 'content-type: application/json' -H 'origin: http://localhost:8088' \
  -d '{"email":"viewer.test@acme.com","password":"viewer-pw-123"}'
curl -s -o /dev/null -w "PATCH application (expect 403): %{http_code}\n" -b $J \
  -X PATCH http://localhost:8088/api/applications/62 \
  -H 'content-type: application/json' -H 'origin: http://localhost:8088' -d '{"notes":"nope"}'
curl -s -o /dev/null -w "POST search       (expect 403): %{http_code}\n" -b $J \
  -X POST http://localhost:8088/api/sourcing/search \
  -H 'content-type: application/json' -H 'origin: http://localhost:8088' -d '{"query":"x","source":"web"}'
curl -s -o /dev/null -w "GET  jobs         (expect 200): %{http_code}\n" -b $J http://localhost:8088/api/jobs
```

- [ ] **Step 4: Check the board in the browser**

Log in as the viewer at `http://localhost:8088` (use a cache-busting
query string, e.g. `?v=2`, or the browser may serve a stale bundle — this
has produced a false "it's broken" reading before). Open a job and
confirm: no **Add candidate**, no drag-and-drop, the read-only note is
visible, and cards still show scores.

- [ ] **Step 5: Confirm chat still answers**

Open a scored candidate as the viewer and ask "why did this candidate
score low?". Expect a real answer. Then ask it to "reject this
candidate": the agent must not be able to — it has no such tool.

- [ ] **Step 6: Clean up**

```bash
docker compose exec -T postgres psql -U recruiter -d recruiter -c \
  "begin; delete from auth_sessions where user_id=(select id from users where email='viewer.test@acme.com'); delete from users where email='viewer.test@acme.com'; commit;"
```

- [ ] **Step 7: Commit any fixes**

If Steps 3-5 revealed a defect, fix it, re-run both suites, and commit.
If everything passed, there is nothing to commit for this task.

---

## Verification checklist

- [ ] `.venv/bin/python -m pytest -q` — green
- [ ] `npm test --prefix recruiter-frontend` — green
- [ ] `npm run --prefix recruiter-frontend lint` — clean
- [ ] `ruff check` on touched files — no new error categories vs baseline
- [ ] A viewer receives 403 on every non-allowlisted mutation, 200 on reads
- [ ] A viewer can chat, and the agent cannot mutate on their behalf
- [ ] A brand-new mutating route is denied to viewers without being listed
