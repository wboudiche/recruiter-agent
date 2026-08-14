# Retry extraction from the kanban card

Date: 2026-08-14
Status: approved (design)

## Problem

When the extraction stage fails, the application stays on `Stage.EXTRACTING`
forever. The card looks exactly the same whether the pipeline is still working
or died twenty minutes ago, and the recruiter has no way to run extraction
again short of deleting the candidate and re-adding the URL.

This is not hypothetical. A single session produced four stranded cards — one
per failure cause (expired LLM token, upstream 429, `ReadTimeout`, and an
Apify run budget that killed the scrape). Each looked identical on the board:
"Extracting", no reason, no action.

## What already exists

`POST /api/applications/{application_id}/retry` (`api/applications.py:225`) is
implemented and tested (`tests/api/test_application_retry.py`). It:

- rejects anything whose stage is not `EXTRACTING` with `409`
- reuses `candidate.raw_extracted["text"]`, so a successful scrape is not
  re-fetched (no second Apify charge)
- re-runs `process_application` as a background task, returning `202`

**No frontend code calls it.** Grepping the frontend for `/retry` outside
generated `api-types.ts` and tests returns nothing. The capability exists; the
affordance does not.

This spec therefore wires up existing behaviour rather than adding a new
pipeline path.

## Design

### 1. Backend — surface the failure reason

`ApplicationRead` (`schemas/application.py:14`) gains one field:

```python
last_error: str | None = None
```

Derived, not stored — the same approach `awaiting_paste` already uses in
`_to_read` (`api/applications.py:109`).

**Rule:** take the application's most recent `event_logs` row, ordered by `id`
descending (not `created_at` — same-second writes tie). If its `event_type`
ends in `.failed`, `last_error` is `payload["error"]`. Otherwise `None`.

Consequences of the rule, all intentional:

- A successful run writes `application.scored` afterwards, so the flag clears
  itself. No cleanup job, no column to keep in sync, no migration.
- `score.failed` and `enrichment.failed` are covered for free, because the
  rule keys off the suffix rather than a specific event type. Scoring failures
  strand cards the same way extraction failures do.
- While a retry is in flight the stale error is still the newest event. The
  UI covers this window optimistically (see below) rather than the API
  inventing a "retrying" state.

**N+1 risk.** `_to_read` runs per application, so a naive per-row lookup issues
one query per card. The list endpoint (`GET /api/jobs/{id}/applications`) must
fetch the latest event for all applications in the response with a single
grouped query and pass the result into `_to_read`. The detail endpoint may
query directly — it handles one row.

### 2. Frontend — the card

`candidate-card.tsx` already renders the `awaiting_paste` affordance ("needs
paste" at line 69, "Needs profile" at line 78). The retry UI sits beside it.

When `last_error` is set, the card shows a one-line reason, truncated, with the
full text in a `title` tooltip (real errors run long:
`HTTP 429 from https://… — {"error":{"message":…}}`).

The **Retry** button appears only when `last_error` is set **and** the stage is
`extracting`. These are two conditions, not one: the standalone re-enrich
endpoint can leave `enrichment.failed` as the newest event on an application
that is already `scored`. Such a card should explain what failed, but offering
Retry there would send the user into a guaranteed `409`.

On click:

1. optimistically switch the card to a "retrying…" state, because `last_error`
   stays stale until the new run writes its own event
2. invalidate `queryKeys.jobApplications(jobId)`
3. let the existing SSE/polling refresh settle the final state

On `409` (stage moved on), surface the endpoint's `detail` as a toast and
refresh. The guard stays server-side; the client does not duplicate it.

### 3. Tests

Backend:

- `last_error` is populated after a failed extraction
- `last_error` is `None` after a successful retry
- the list endpoint does not regress into N+1 (assert query count)

Frontend, matching the existing kanban test style
(`bulk-actions-bar.test.tsx`):

- card renders reason + Retry when `last_error` is set and stage is
  `extracting`
- card renders the reason but **no** Retry when `last_error` is set on a
  `scored` application (the re-enrich case)
- card renders neither when `last_error` is absent
- clicking Retry posts to `/api/applications/{id}/retry`

## Out of scope

Deliberately excluded to keep this one reviewable change:

- automatic background retry (the LLM client already retries transient 429/5xx
  at the HTTP layer; this is the human-in-the-loop escape hatch)
- retry from stages other than `EXTRACTING` — the endpoint's existing `409`
  guard stands
- a dedicated `FAILED` kanban column
- bulk retry across selected cards

## Verification

- `pytest` and the frontend suite green, no new lint errors versus baseline
- manual check against a real stuck card: fail an extraction, confirm the card
  shows the reason, click Retry, watch it reach `scored`
