# Viewer permission matrix — Slice 2

Date: 2026-08-15
Status: approved (design)
Follows: `2026-08-14-users-and-roles-design.md` (Slice 1)

## Problem

Slice 1 shipped three roles and gated the routes that read or write
credentials, but deliberately stopped there: recruiter and viewer are
identical in practice. A viewer today can add candidates, validate,
reject, source new people, email them, and spend LLM credits — everything
a recruiter can do. The Users tab says so, but the role selector still
offers "Viewer", which implies a restriction that does not exist.

This slice makes viewer mean read-only.

Recruiter needs no new restrictions: Slice 1 already put user management
and the credential-bearing routes behind admin, and everything else is
recruiting work.

## The trap: chat can mutate

`agent/tools.py` gives the chat agent eleven tools. Eight are reads and
searches; three are writes — `save_note`, `validate_application`,
`reject_application` (`tools.py:358-388`).

So `POST /api/applications/{id}/chat` looks like a conversation endpoint
and carries write capability. Two consequences shape the design:

- A rule as simple as "viewers cannot POST" would also remove chat, which
  is the single most useful thing a hiring manager can do with a
  shortlist.
- An allowlist that permits chat without touching the agent leaves a hole
  wide enough to validate and reject candidates through conversation
  while `PATCH /applications/{id}` is gated shut.

Chat is therefore allowed at the route and constrained inside the agent.

## Design

### 1. Enforcement: an app-level dependency, default-deny

**Semantics:** a viewer is refused any mutating method unless the route is
explicitly allowlisted. A route added later is denied by default —
someone has to opt it in deliberately, rather than it silently shipping
open.

**Mechanism: an app-level dependency, not ASGI middleware.** Middleware
runs before dependency resolution, so it would have to parse the session
cookie and query the database itself — a second lookup per request, plus
a duplicate copy of the dev-bypass logic that could drift from
`require_user`. An app-level dependency runs after routing, can read the
route template, and shares `require_user`'s work through FastAPI's
per-request dependency cache.

To make that sharing real, `api/deps.py` splits:

- `maybe_user(...) -> User | None` — resolves dev bypass, then the
  session cookie. **Never raises.**
- `require_user(...)` — `maybe_user` plus the existing 401. Behaviour is
  unchanged for every current caller, including the `is_active` check.

The guard is registered once, so it covers routers that do not exist yet:

```python
app = FastAPI(lifespan=lifespan, dependencies=[Depends(viewer_readonly_guard)])
```

It matches on `request.scope["route"].path` — the **template**
(`/api/applications/{application_id}/chat`), not the concrete path — so
no regex has to cope with ids embedded in URLs. Verified: app-level
dependencies run after routing and see the resolved route.

Anonymous requests pass straight through. The guard's job is role
enforcement, not authentication; the route's own dependencies still
return 401 where they should, and login and the OIDC callback are
unaffected.

**The allowlist, complete:**

| Method + route template | Why |
|---|---|
| `POST /api/applications/{application_id}/chat` | Read-only for viewers via §2 |
| `POST /api/auth/password` | Every role changes its own password |
| `POST /api/auth/logout` | Refusing logout would be absurd |
| `POST /api/auth/login/password` | Anonymous anyway; listed so it cannot regress |

Everything else stays denied for viewers, including the endpoints that
are arguably reads: `POST /api/sourcing/search`,
`POST /api/jobs/criteria/suggest`,
`POST /api/sourcing/jobs/{job_id}/query/suggest`. They spend search and
LLM credits and exist to source *new* candidates — recruiter work, not
shortlist-viewing. Also denied: `draft-email`, `notify`, `retry`,
`re-enrich`, `undo`, `upload`, and adding candidates.

Refusals return **403** with detail `"read-only role"`, distinguishing
them from the 401 of an expired session.

### 2. The chat agent

Because the route is allowlisted, the write capability is removed inside
the agent.

`TOOLS` (`agent/tools.py:222`, extended at `:358`) is currently a module
constant consumed by `agent/chat.py:121`. It gains a role-aware
accessor — `tools_for(role) -> list[ToolDef]` — which omits
`save_note`, `validate_application` and `reject_application` for a
viewer. A model cannot call a tool it was never given, so this is a real
boundary rather than a prompt instruction.

The read and search tools remain, so "why did this candidate score low?"
still works.

**Second, deliberately redundant layer:** the executors for those three
tools re-check the role and refuse. If a later refactor rebuilds the tool
list and forgets the filter, the mutation still does not happen.
Authorization is the one place where belt-and-braces earns its keep.

That layer needs the caller's role, which `ToolContext`
(`agent/tools.py:20`) does not currently carry — it holds the session,
application id, undo store, and frontend events. It gains a `role: Role`
field, populated where the context is built in `agent/chat.py:111`, which
means threading the role from the chat route into `run_chat_turn`. The
dataclass docstring already anticipates this: "Future fields (request_id,
principal, dry_run) plug in here without growing the agent loop's
dispatch."

`role` rather than the whole `User`: the executors need an authorization
level, not an identity, and a narrower field is harder to misuse later
for something it was not meant for.

### 3. Frontend

`role` already reaches the client on `GET /api/auth/me`. A single
`canWrite = role !== "viewer"` drives the hiding, mirroring Slice 1's
`isAdmin`.

Hidden for viewers: **Add candidate**, **Validate**, **Reject**,
**Notify**, **Retry**, the **Search** tab, and kanban drag-and-drop
(`isDraggable` gains `&& canWrite`). Chat stays.

One line of muted copy on the job board explains the account is
read-only, so an empty toolbar reads as a permission boundary rather than
a broken page.

This is cosmetic. The 403s are the gate, and the tests assert the API
directly rather than trusting the UI to hide anything.

## Out of scope

- Per-record ownership ("my candidates") — a different feature from role
  tiers.
- Changing what recruiter or admin may do. Slice 1 settled both.
- Read-gating: viewers keep `GET` access to everything they can see
  today, including `GET /api/settings` (the notify wizard reads it, and
  it returns only `has_*` booleans).
- Per-account login throttling and the other follow-ups recorded on
  PR #5.

## Testing

The negative cases are the point, so they are parametrised across every
mutating route rather than sampled:

- For each mutating route in the app, a viewer receives 403 and a
  recruiter does not. Building the list by **introspecting `app.routes`**
  rather than hardcoding it means a new route joins the test
  automatically.
- **Fail-closed test:** register a throwaway mutating route on a test app
  and assert a viewer is refused it without anyone adding it to a list.
  This is the property the entire design exists for, and the one most
  likely to rot silently.
- Every allowlisted route is reachable by a viewer — otherwise the
  allowlist could be quietly empty and the suite would still pass.
- Anonymous requests still reach `POST /api/auth/login/password` (the
  guard does not break authentication).
- Viewer chat returns 200, and the tool list it produces contains none of
  the three write tools.
- Calling each write executor directly with a viewer context refuses,
  proving the second layer independently of the first.

Frontend: a viewer sees no write controls on a job board; a recruiter
sees them. Both directions, so removing the gating fails a test.

## Verification

- `pytest` and the frontend suite green; no new lint errors versus
  baseline.
- Manual, against the running stack: create a viewer, log in as them,
  confirm the board renders read-only, confirm chat answers a question,
  and confirm `PATCH /api/applications/{id}` returns 403 while
  `GET /api/jobs` returns 200.
