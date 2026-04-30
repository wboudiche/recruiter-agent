# Plan A — Post-merge Follow-ups

**Date:** 2026-04-30
**Source:** Final whole-branch code review of `feature/plan-a-backend` (Tasks 10–26 + live-wire).
**Status:** punch list. Items are **not** blocking Plan B. Pick up as time allows or as the frontend (Plan B) starts surfacing them.

## Already fixed inline post-review (commit forthcoming)

- **I1 — Router `lstrip("www.")` was a character-strip, not a prefix-strip.** Replaced with `removeprefix("www.")`. Added regression test for `wwwapp.com`-style hosts.
- **m1 — Invalid URL in `add_candidate` returned 500.** Now wraps `_route_url(...)` in `try/except ValueError` and raises `HTTPException(status_code=422, detail=...)`. Added regression test.
- **I3 — Mid-file imports in `candidates.py`.** Consolidated all imports at the top of the file.

## High-risk, deferred (need design call)

### C2 — Application stage stuck at `EXTRACTING` after pipeline failure

**File:** `src/recruiter/pipeline/orchestrator.py`

When `extract_candidate` or `score_candidate` raises, the orchestrator writes an `EventLog`, publishes an error event on the bus, and returns. But `Application.stage` stays at `EXTRACTING` forever. The kanban will show "Extracting…" with no indication of failure.

**Options:**
1. Add `Stage.FAILED = "failed"` to the enum, generate a migration that uses `ALTER TYPE stage ADD VALUE 'failed'` (non-transactional in Postgres — needs `transaction_per_migration = False`), and set `app.stage = Stage.FAILED` in both `except` branches. Add an `Application.error_phase` and `error_message` column for context.
2. Keep the design as-is (stage stays `EXTRACTING`) and require Plan B's UI to listen for `type=error` events on the SSE bus to render an error overlay.

Option 2 is cheaper but couples the frontend to the SSE event for correctness. Option 1 is the cleaner data model. Decide before Plan B's kanban implementation.

### C1 — `score` variable bound across `except`/`return` boundary

**File:** `src/recruiter/pipeline/orchestrator.py:70`

The final `bus.publish` referencing `score.score` is outside the `async with` block. It is **safe today** because the `except` blocks return before reaching it, but a future refactor that removes any of those `return` statements becomes a `NameError`. Move the publish inside the `with` block, immediately after `await session.commit()`.

## Medium-risk, deferred

### I7 — No tests for orchestrator failure paths

**File:** `tests/unit/test_orchestrator.py`

Only the happy path is tested. Add:
- Extract failure: LLM raises → assert stage stays at `EXTRACTING` (or `FAILED` if C2 is fixed), `EventLog` written with `event_type="extract.failed"`, error event published.
- Score failure: same shape but with `event_type="score.failed"`.

This locks down the failure semantics regardless of which option is chosen for C2.

### I2 — `get_llm` imports `_cipher` (private symbol) from `recruiter.api.settings`

**File:** `src/recruiter/api/candidates.py:38`

Cross-module private import. Either:
- Expose `recruiter.api.settings.get_cipher() -> SecretCipher` as a public helper, or
- Move the cipher factory to `recruiter.crypto` (alongside `SecretCipher`) so any caller reads config and constructs the cipher consistently.

### I5 — `EventBus` singleton lives in `candidates.py`

**Files:** `src/recruiter/api/candidates.py` (defines `_singleton_bus`, `get_event_bus`), `src/recruiter/api/events.py` (imports from `candidates.py`)

The bus is infrastructure, the candidates module is a route handler. `events.py` should not depend on a sibling route module. Move `_singleton_bus` and `get_event_bus` to `recruiter/api/deps.py` (or a new `recruiter/bus.py`).

### I4 — GitHub fetcher is unauthenticated

**Files:** `src/recruiter/pipeline/fetchers/github.py`, `src/recruiter/api/candidates.py:_route_url`

`fetch_github(url, *, token=None)` accepts a token parameter that is never passed. Unauthenticated GitHub API has 60 requests/hour. Add `RECRUITER_GITHUB_TOKEN` to `Config` and thread it through `_route_url → fetch_github(url, token=...)`. (Alternatively, store it in the `Settings` row alongside the other secrets.)

### I8 — `ScoreBreakdownItem` defined twice

**Files:** `src/recruiter/schemas/application.py` (no validators), `src/recruiter/schemas/extraction.py` (with `ge`/`le`)

Both definitions are structurally compatible. Promote the validated one to a shared location (or have `application.py` import from `extraction.py`) so there's a single source of truth.

### I6 — `async_sessionmaker` rebuilt per request

**File:** `src/recruiter/api/deps.py`

`get_session` constructs `async_sessionmaker(engine, expire_on_commit=False)` on every request. Cheap, but inconsistent with `db.py`'s existing `get_session_factory(engine)` helper. Use it.

## Low-risk, deferred

### m2 — `OpenAICompatLLMClient` is never `aclose()`d

**File:** `src/recruiter/llm/openai_compat.py`

Each request through `get_llm` constructs a new `httpx.AsyncClient` that's never closed. Cleanest fix: register a FastAPI lifespan hook that holds a singleton `OpenAICompatLLMClient` per-config and closes it on shutdown. (Anthropic SDK manages its own lifecycle so isn't affected.)

### m3 — `_GITHUB_PROFILE_RE` rejects valid usernames with underscores

**File:** `src/recruiter/pipeline/fetchers/github.py:17`

GitHub allows underscores in handles. Update regex to `[A-Za-z0-9_-]+`. Decide what to do with `github.com/org/repo` URLs (currently 422; could fall back to webpage fetcher).

### m5 — `SettingsUpdate.default_llm_provider` accepts any string

**File:** `src/recruiter/schemas/settings.py:19`

Change to `Literal["anthropic", "local"] | None` so a typo at PUT time returns 422 instead of being stored and 503-ing later at candidate creation.

### m6 — SSE has no keepalive

**File:** `src/recruiter/api/events.py`

Idle SSE connections will be killed by reverse proxies after 30–60s. Wrap the `queue.get()` with `asyncio.wait_for(..., timeout=15.0)` and emit a comment-event on `TimeoutError`.

### m7 — Plan documentation drift

**File:** `docs/superpowers/plans/2026-04-29-plan-a-backend-pipeline.md` (Task 1, Step 4)

Plan still shows `get_config` without `@lru_cache`. Real code has `@lru_cache(maxsize=1)`. Update the plan snippet for future re-implementers.

## Final-pass review verdict

> "Production-quality for a Phase 1 MVP. Architecture is sound, crypto and session handling are correct, test suite is meaningfully comprehensive for the happy path."

— Final whole-branch code review, 2026-04-30
