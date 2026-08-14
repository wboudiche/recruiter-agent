# Retry Extraction From Card — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a recruiter see why extraction failed and re-run it from the kanban card, instead of the card sitting on "Extracting" forever with no explanation and no recovery.

**Architecture:** The retry endpoint (`POST /api/applications/{id}/retry`) already exists and is tested — no backend pipeline work. We add one derived field, `last_error`, to `ApplicationRead`, computed from the newest `event_logs` row for the application (same derived-not-stored pattern as the existing `awaiting_paste`). The card reads that field to render a reason line, and a Retry button when the application is still recoverable.

**Tech Stack:** FastAPI + SQLAlchemy 2 (async) + Pydantic v2 on the backend; React 18 + TanStack Query + Vitest + Testing Library on the frontend. Tests via `pytest` and `npm test` (vitest).

## Global Constraints

- Python line length ≤ 100 chars (ruff `E501`); match the repo's existing style — do not reformat untouched lines.
- No Alembic migration. `last_error` is derived at read time, never stored.
- Do not modify `POST /api/applications/{id}/retry`. Its `409` guard for non-`EXTRACTING` stages is the contract this feature relies on.
- Backend tests run with `.venv/bin/python -m pytest`; frontend tests with `npm test --prefix recruiter-frontend`.
- Run every command from the repo root `/home/walidboudiche/recruiter-agent`.
- Commit after each task. Branch is `feat/retry-extraction-from-card`.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/recruiter/schemas/application.py` | `ApplicationRead` response shape | Modify — add `last_error` |
| `src/recruiter/api/applications.py` | Derive `last_error`; batch-load it for the list endpoint | Modify — `_to_read`, `_latest_errors`, both read endpoints |
| `tests/api/test_application_last_error.py` | Backend behaviour of the new field | Create |
| `recruiter-frontend/src/hooks/use-job-applications.ts` | TS type mirroring `ApplicationRead` | Modify — add `last_error` |
| `recruiter-frontend/src/components/kanban/candidate-card.tsx` | Reason line + Retry button | Modify |
| `recruiter-frontend/src/components/kanban/candidate-card.test.tsx` | Card rendering + retry POST | Create |

---

### Task 1: Derive `last_error` on the application read model

**Files:**
- Modify: `src/recruiter/schemas/application.py:32` (after `awaiting_paste`)
- Modify: `src/recruiter/api/applications.py:109` (`_to_read`), `:95` (list endpoint), `:40` (detail endpoint)
- Test: `tests/api/test_application_last_error.py` (create)

**Interfaces:**
- Consumes: `Application`, `EventLog` models; existing `_to_read(app_row)`.
- Produces:
  - `ApplicationRead.last_error: str | None`
  - `_to_read(app_row: Application, last_error: str | None = None) -> ApplicationRead`
  - `async _latest_errors(session: AsyncSession, application_ids: list[int]) -> dict[int, str]`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_application_last_error.py`:

```python
"""`last_error` surfaces why the pipeline stopped, so the UI can say more
than "Extracting" and decide whether Retry is worth offering."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.models import Application, Candidate, EventLog, Job, Stage


async def _seed(session: AsyncSession) -> Application:
    job = Job(title="T", description="D", criteria=[])
    candidate = Candidate(full_name=None)
    session.add_all([job, candidate])
    await session.flush()
    app_row = Application(job_id=job.id, candidate_id=candidate.id, stage=Stage.EXTRACTING)
    session.add(app_row)
    await session.commit()
    return app_row


@pytest.mark.asyncio
async def test_last_error_reports_the_newest_failure(
    api_client: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_row = await _seed(db_session_with_schema)
    db_session_with_schema.add(EventLog(
        application_id=app_row.id,
        event_type="extract.failed",
        payload={"error": "HTTP 429 rate-limited"},
    ))
    await db_session_with_schema.commit()

    body = (await api_client.get(f"/api/applications/{app_row.id}")).json()

    assert body["last_error"] == "HTTP 429 rate-limited"


@pytest.mark.asyncio
async def test_last_error_clears_once_a_later_event_succeeds(
    api_client: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    """A successful retry writes a newer event; the flag must self-heal
    rather than pin the card to a stale failure."""
    app_row = await _seed(db_session_with_schema)
    db_session_with_schema.add(EventLog(
        application_id=app_row.id, event_type="extract.failed", payload={"error": "boom"},
    ))
    await db_session_with_schema.commit()
    db_session_with_schema.add(EventLog(
        application_id=app_row.id, event_type="application.scored", payload={"score": 42},
    ))
    await db_session_with_schema.commit()

    body = (await api_client.get(f"/api/applications/{app_row.id}")).json()

    assert body["last_error"] is None


@pytest.mark.asyncio
async def test_last_error_is_none_when_nothing_has_happened(
    api_client: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_row = await _seed(db_session_with_schema)

    body = (await api_client.get(f"/api/applications/{app_row.id}")).json()

    assert body["last_error"] is None


@pytest.mark.asyncio
async def test_list_endpoint_includes_last_error(
    api_client: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_row = await _seed(db_session_with_schema)
    db_session_with_schema.add(EventLog(
        application_id=app_row.id, event_type="score.failed", payload={"error": "ReadTimeout"},
    ))
    await db_session_with_schema.commit()

    rows = (await api_client.get(f"/api/jobs/{app_row.job_id}/applications")).json()

    assert [r["last_error"] for r in rows if r["id"] == app_row.id] == ["ReadTimeout"]


@pytest.mark.asyncio
async def test_list_endpoint_does_not_query_per_application(
    api_client: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    """`_to_read` runs per row, so a per-row error lookup would be N+1.
    The count must not grow with the number of applications on the board."""
    from sqlalchemy import event as sa_event

    first = await _seed(db_session_with_schema)
    for _ in range(4):
        extra = Application(
            job_id=first.job_id, candidate_id=first.candidate_id, stage=Stage.EXTRACTING,
        )
        db_session_with_schema.add(extra)
    await db_session_with_schema.commit()

    engine = db_session_with_schema.bind
    assert engine is not None
    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    sa_event.listen(engine.sync_engine, "before_cursor_execute", _record)
    try:
        await api_client.get(f"/api/jobs/{first.job_id}/applications")
    finally:
        sa_event.remove(engine.sync_engine, "before_cursor_execute", _record)

    event_log_queries = [s for s in statements if "event_logs" in s.lower()]
    assert len(event_log_queries) <= 1, f"expected one batched query, got {len(event_log_queries)}"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/api/test_application_last_error.py -v`
Expected: FAIL — `KeyError: 'last_error'` (the field does not exist yet).

- [ ] **Step 3: Add the field to the schema**

In `src/recruiter/schemas/application.py`, directly after `awaiting_paste: bool = False`:

```python
    # Why the pipeline stopped, when it did. Derived from the newest
    # event_logs row rather than stored — see `_latest_errors`.
    last_error: str | None = None
```

- [ ] **Step 4: Derive it in the API layer**

In `src/recruiter/api/applications.py`, add this helper just above `_to_read`:

```python
async def _latest_errors(
    session: AsyncSession, application_ids: list[int]
) -> dict[int, str]:
    """Map application id → error message, for those whose most recent
    event is a failure.

    Ordered by `id` rather than `created_at`: two events written in the
    same second tie on the timestamp, and a tie here would flip a card
    between "failed" and "fine" at random.

    One query for the whole batch — `_to_read` runs per row, so a
    per-row lookup would be N+1 across a full board.
    """
    if not application_ids:
        return {}
    newest = (
        select(EventLog.application_id, func.max(EventLog.id).label("max_id"))
        .where(EventLog.application_id.in_(application_ids))
        .group_by(EventLog.application_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(EventLog).join(newest, EventLog.id == newest.c.max_id)
        )
    ).scalars().all()
    out: dict[int, str] = {}
    for row in rows:
        if not row.event_type.endswith(".failed") or row.application_id is None:
            continue
        error = (row.payload or {}).get("error")
        if error:
            out[row.application_id] = str(error)
    return out
```

Add the imports this needs at the top of the file — `func` alongside the existing `select` import, and `EventLog` alongside the existing models import:

```python
from sqlalchemy import func, select
from recruiter.models import Application, Candidate, EventLog, Stage
```

Change the `_to_read` signature to accept the value:

```python
def _to_read(app_row: Application, last_error: str | None = None) -> ApplicationRead:
```

and pass it through in the `ApplicationRead(...)` construction, after `awaiting_paste=awaiting_paste,`:

```python
        last_error=last_error,
```

- [ ] **Step 5: Wire both read endpoints**

In `get_application` (`applications.py:40`), replace `return _to_read(app_row)` with:

```python
    errors = await _latest_errors(session, [app_row.id])
    return _to_read(app_row, errors.get(app_row.id))
```

In `list_applications_for_job` (`applications.py:95`), replace `return [_to_read(r) for r in rows]` with:

```python
    errors = await _latest_errors(session, [r.id for r in rows])
    return [_to_read(r, errors.get(r.id)) for r in rows]
```

Leave `patch_application`'s `return _to_read(app_row)` alone — the default `None` is correct there, since a stage edit is not a pipeline failure.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/api/test_application_last_error.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 7: Run the whole backend suite and lint**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check --output-format=concise src/recruiter/api/applications.py src/recruiter/schemas/application.py tests/api/test_application_last_error.py`
Expected: all tests pass; ruff reports no NEW errors versus the pre-change baseline for those files (check the baseline first with `git stash` if unsure).

- [ ] **Step 8: Commit**

```bash
git add src/recruiter/schemas/application.py src/recruiter/api/applications.py tests/api/test_application_last_error.py
git commit -m "feat(api): expose last_error so the UI can explain a stalled pipeline"
```

---

### Task 2: Show the reason and a Retry button on the card

**Files:**
- Modify: `recruiter-frontend/src/hooks/use-job-applications.ts:31` (after `awaiting_paste`)
- Modify: `recruiter-frontend/src/components/kanban/candidate-card.tsx`
- Test: `recruiter-frontend/src/components/kanban/candidate-card.test.tsx` (create)

**Interfaces:**
- Consumes: `ApplicationRead.last_error` from Task 1; `api()` and `ApiError` from `@/lib/api`; `queryKeys.jobApplications(jobId)` from `@/lib/query-keys`.
- Produces: `CandidateCard` accepting an optional `jobId?: number` prop used to invalidate the board query after a retry.

- [ ] **Step 1: Write the failing test**

Create `recruiter-frontend/src/components/kanban/candidate-card.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { CandidateCard } from "./candidate-card";
import type { ApplicationRead } from "@/hooks/use-job-applications";

const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: apiMock };
});

function baseApp(overrides: Partial<ApplicationRead> = {}): ApplicationRead {
  return {
    id: 68, job_id: 8, candidate_id: 68, stage: "extracting",
    score: null, score_breakdown: null, score_rationale: null, notes: null,
    validated_at: null, invited_at: null, scheduled_at: null, rejected_at: null,
    created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    awaiting_paste: false, last_error: null,
    ...overrides,
  };
}

function renderCard(application: ApplicationRead) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CandidateCard application={application} jobId={8} draggable={false} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiMock.mockReset();
  apiMock.mockResolvedValue({ application_id: 68 });
});

describe("CandidateCard retry", () => {
  it("shows the failure reason and a Retry button when extraction stalled", () => {
    renderCard(baseApp({ last_error: "HTTP 429 rate-limited upstream" }));

    expect(screen.getByText(/rate-limited upstream/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("shows neither when there is no error", () => {
    renderCard(baseApp());

    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  it("explains the error but hides Retry once the application has moved on", () => {
    // Re-enrich can fail on an already-scored application. Retrying there
    // is a guaranteed 409, so the button must not be offered.
    renderCard(baseApp({ stage: "scored", score: 26, last_error: "enrichment boom" }));

    expect(screen.getByText(/enrichment boom/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  it("posts to the retry endpoint when clicked", async () => {
    renderCard(baseApp({ last_error: "boom" }));

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() =>
      expect(apiMock).toHaveBeenCalledWith("/api/applications/68/retry", { method: "POST" }),
    );
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test --prefix recruiter-frontend -- candidate-card`
Expected: FAIL — no Retry button in the DOM, and `last_error` is not a known property of `ApplicationRead`.

- [ ] **Step 3: Add the field to the TS type**

In `recruiter-frontend/src/hooks/use-job-applications.ts`, after `awaiting_paste: boolean;`:

```ts
  /** Why the pipeline stopped, when it did. Null when healthy. */
  last_error?: string | null;
```

- [ ] **Step 4: Implement the card changes**

In `recruiter-frontend/src/components/kanban/candidate-card.tsx`:

Add imports at the top, next to the existing ones:

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
```

Add `jobId` to the `Props` interface:

```tsx
  jobId?: number;
```

and to the destructured parameters, after `application`:

```tsx
  jobId,
```

Inside the component, above the `return`:

```tsx
  const qc = useQueryClient();
  const lastError = application.last_error ?? null;
  // Retry needs BOTH conditions. The re-enrich endpoint can leave a
  // failure event on an application that has already scored; the retry
  // endpoint rejects anything that is not EXTRACTING, so offering the
  // button there would only produce a 409.
  const canRetry = Boolean(lastError) && application.stage === "extracting";

  const retryMut = useMutation({
    mutationFn: () => api(`/api/applications/${application.id}/retry`, { method: "POST" }),
    onSuccess: () => {
      toast.success("Extraction restarted");
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "Retry failed");
    },
    onSettled: () => {
      if (jobId !== undefined) {
        qc.invalidateQueries({ queryKey: queryKeys.jobApplications(jobId) });
      }
    },
  });
```

Then render it. Inside the `<Link>`, immediately after the closing `)}` of the existing spinner badge block, add:

```tsx
        {!compact && lastError && (
          <div className="space-y-1">
            <p
              className="text-xs text-destructive truncate"
              title={lastError}
            >
              ⚠ {lastError}
            </p>
            {canRetry && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={retryMut.isPending}
                onClick={(e) => {
                  // The whole card is a <Link>; without this the click
                  // navigates to the detail page instead of retrying.
                  e.preventDefault();
                  e.stopPropagation();
                  retryMut.mutate();
                }}
              >
                {retryMut.isPending ? "Retrying…" : "Retry"}
              </Button>
            )}
          </div>
        )}
```

Finally, suppress the misleading spinner while an error is showing — change the existing spinner condition from:

```tsx
        {!compact && !awaitingPaste &&
          (application.stage === "extracting" || application.stage === "enriching") && (
```

to:

```tsx
        {!compact && !awaitingPaste && !lastError &&
          (application.stage === "extracting" || application.stage === "enriching") && (
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npm test --prefix recruiter-frontend -- candidate-card`
Expected: PASS, 4 tests.

- [ ] **Step 6: Thread `jobId` from the board down to the card**

`KanbanBoard` already receives `jobId?: number` (`kanban-board.tsx:31`), but `KanbanColumn` does not, so the prop has to be passed through one level. Without this the board will not refresh after a retry — the mutation fires, but the card keeps showing the stale error until the next poll.

In `recruiter-frontend/src/components/kanban/kanban-column.tsx`, add to the `Props` interface (line 18–26), after `applications`:

```tsx
  jobId?: number;
```

Add it to the destructured parameters of `KanbanColumn` alongside `applications`:

```tsx
  jobId,
```

Then pass it to the card at line 78:

```tsx
          <CandidateCard
            key={app.id}
            application={app}
            jobId={jobId}
            candidateName={candidates?.get(app.candidate_id)?.full_name ?? undefined}
            density={density}
            selected={selected?.has(app.id) ?? false}
            onShiftClick={onShiftClick}
          />
```

In `recruiter-frontend/src/components/kanban/kanban-board.tsx`, add `jobId={jobId}` to the `<KanbanColumn>` element at line 105:

```tsx
            <KanbanColumn
              key={c.stage}
              title={c.title}
              stage={c.stage}
              applications={grouped.get(c.stage) ?? []}
              jobId={jobId}
              candidates={candidates}
              density={density}
```

Leave the remaining props on that element as they are.

- [ ] **Step 7: Run the full frontend suite and typecheck**

Run: `npm test --prefix recruiter-frontend && npm run --prefix recruiter-frontend typecheck`
Expected: all tests pass, no TypeScript errors.

- [ ] **Step 8: Commit**

```bash
git add recruiter-frontend/src/hooks/use-job-applications.ts recruiter-frontend/src/components/kanban/candidate-card.tsx recruiter-frontend/src/components/kanban/candidate-card.test.tsx recruiter-frontend/src/components/kanban/kanban-column.tsx recruiter-frontend/src/components/kanban/kanban-board.tsx
git commit -m "feat(kanban): show why extraction failed and offer Retry on the card"
```

---

### Task 3: Verify against a real stalled card

**Files:** none — this is manual verification against the running stack.

**Interfaces:**
- Consumes: everything from Tasks 1 and 2.
- Produces: no code. A confirmed end-to-end path, or a defect to fix before merge.

- [ ] **Step 1: Rebuild and restart the stack**

```bash
docker compose build backend frontend && docker compose up -d --force-recreate
```

- [ ] **Step 2: Manufacture a failure**

Point the LLM at a model that does not exist, so extraction fails fast and deterministically:

```bash
docker compose exec -T postgres psql -U recruiter -d recruiter -c \
  "update settings set model_overrides = jsonb_set(coalesce(model_overrides,'{}')::jsonb, '{local_model}', '\"does/not-exist\"') where id = 1;"
```

- [ ] **Step 3: Add a candidate and confirm the card explains itself**

In the UI at `http://localhost:8088`, open a job, click **Add candidate → Paste**, paste any text, submit. Within a few seconds the card should show a `⚠` reason line (a 400/404 model error) and a **Retry** button — not an endless "Extracting profile…" spinner.

- [ ] **Step 4: Restore the working model**

```bash
docker compose exec -T postgres psql -U recruiter -d recruiter -c \
  "update settings set model_overrides = jsonb_set(coalesce(model_overrides,'{}')::jsonb, '{local_model}', '\"openai/gpt-oss-20b:free\"') where id = 1;"
```

- [ ] **Step 5: Click Retry and confirm recovery**

The card should show "Retrying…", then progress to `scored` without the candidate being re-added. Confirm the error line disappears — that is `last_error` self-healing via the newer event.

- [ ] **Step 6: Clean up the test candidate**

Delete the candidate created in Step 3 from the board so the job is left as it was found.

- [ ] **Step 7: Commit any fixes**

If Steps 3–5 revealed a defect, fix it, re-run both suites, and commit. If everything passed, there is nothing to commit for this task.

---

## Verification checklist

- [ ] `.venv/bin/python -m pytest -q` — green
- [ ] `npm test --prefix recruiter-frontend` — green
- [ ] `npm run --prefix recruiter-frontend typecheck` — clean
- [ ] `ruff check` on touched files — no new errors versus baseline
- [ ] Manual: a failed extraction shows its reason and recovers via Retry
