# Add-Candidate Search (Plan G) — Design

**Author:** walid + claude
**Date:** 2026-05-05
**Status:** approved, ready for implementation plan

## Goal

Let the recruiter discover candidates directly from the **Add Candidate** slide-over on a job's kanban — not just via the chat panel inside a specific application. Adds a fourth tab "Search" with multi-source query (LinkedIn / GitHub / Web checkboxes), one query input, and a results stack. Click "Add" on a card → application created on the current job.

This unblocks empty jobs (no applications yet → no chat panel → no search surface in Plan F) and matches the natural place users look for "find me candidates".

## Scope

### In scope (v1)

- New backend endpoint `POST /api/sourcing/search` that accepts an array of sources, runs them concurrently, returns merged results with per-source error reporting
- Refactor of `agent/tools.py` to share search logic with the new endpoint via a new `sourcing/search.py` module (single source of truth)
- New "Search" tab in the Add Candidate slide-over with three toggleable source pills, query input, results stack
- Reuses Plan F's `SearchResultCard` component — Add button POSTs to the existing `/api/jobs/{job_id}/candidates` endpoint
- Per-card "Added ✓" persistent state on `SearchResultCard` after a successful add

### Out of scope (deferred)

- Removing the chat-based search from Plan F — the two are additive (chat for refinement, add-candidate for discovery)
- De-duplication against existing job applications (still a Plan F-level limitation; clicking Add twice still creates duplicates)
- Persisting searches across slide-over close (results vanish; user re-runs)
- Saved searches / search history
- Pagination beyond `limit_per_source` (max 30 per source v1; Google CSE caps at 10 anyway)
- Per-source result re-ordering / interleaving heuristics — backend returns results in source order

## Architecture

```
┌──────────────────┐  POST /api/sourcing/search       ┌──────────────────┐
│ AddCandidate     │ ────────────────────────────────►│ api/sourcing.py  │
│ Panel → "Search" │  {sources: [...], query, limit}  │  multi-source    │
│   tab            │ ◄───────────────────────────────│  fan-out         │
│ (pills + query   │  {results: [...],                └────────┬─────────┘
│  + cards)        │   errors: [...]}                          │
└──────────────────┘                              asyncio.gather│
                                                                ▼
                                       ┌──────────────────────────┐
                                       │  sourcing/search.py      │
                                       │  search_one_source(...)  │
                                       │  (shared with chat tools)│
                                       └──────┬──────────┬────────┘
                                              ▼          ▼
                                       Google CSE      GitHub
                                       (LinkedIn,       client
                                        Web)
```

**Single shared implementation:** the per-source search logic is extracted from `agent/tools.py` into `sourcing/search.py`. Plan F's chat tools become thin wrappers around `search_one_source`; the new HTTP endpoint also calls it. Removes the inline duplication that already existed in `_run_provider_search` and `_search_github`.

**Concurrency:** the endpoint runs requested sources in parallel via `asyncio.gather(*tasks, return_exceptions=True)`. A failure in one source (e.g. LinkedIn config missing) doesn't block the others.

**No state on the slide-over:** results live in component-local React state during the open session. Closing and re-opening the panel resets — match the existing tabs' behavior.

## Components

### Backend

1. **`src/recruiter/sourcing/search.py`** (new)

   ```python
   async def search_one_source(
       source: Literal["linkedin", "github", "web"],
       query: str,
       limit: int,
       *,
       settings: SettingsRow | None,
   ) -> list[SearchResult]:
       """Run search against the chosen source.

       LinkedIn prepends `site:linkedin.com/in/` to the query and dispatches
       to the configured provider (GoogleCSE in v1).
       Web passes the query verbatim to the provider.
       GitHub uses GitHubSearchClient directly (provider registry is
       LinkedIn/Web-only).

       Sets SearchResult.source on each card to match the requested source
       (provider returns generic "web" which is overridden here).

       Raises SearchError when settings unset, provider missing, or the
       upstream call fails. Caller decides whether to surface or partial-fail.
       """
   ```

2. **`src/recruiter/api/sourcing.py`** (new)

   - Router `POST /api/sourcing/search` gated with `Depends(require_user)`
   - Pydantic request:

     ```python
     class SearchRequest(BaseModel):
         sources: list[Literal["linkedin", "github", "web"]] = Field(min_length=1)
         query: str = Field(min_length=1)
         limit_per_source: int = Field(default=5, ge=1, le=30)
     ```

   - Pydantic response:

     ```python
     class SearchErrorItem(BaseModel):
         source: str
         reason: str
         transient: bool

     class SearchResponse(BaseModel):
         results: list[SearchResult]   # reuse the existing dataclass
         errors: list[SearchErrorItem]
     ```

   - Implementation:
     - Load Settings row
     - `tasks = [search_one_source(s, query, limit, settings=settings) for s in sources]`
     - `outcomes = await asyncio.gather(*tasks, return_exceptions=True)`
     - For each (source, outcome): `list` → flatten into results; `SearchError` → append to errors with `transient` flag; other Exception → append with `transient=true`, `reason="internal error: <Class>"`

   - Mounted in `main.py` like every other router

3. **`src/recruiter/agent/tools.py`** (refactor — backwards-compatible)

   - `_run_provider_search` body becomes: `results = await search_one_source(source, query, limit, settings=settings)` followed by the existing ToolContext.frontend_events emission and summary formatting
   - `_search_github` similarly thinned
   - All existing chat tool tests pass unchanged (same behavior, fewer lines)

4. **`src/recruiter/main.py`** — adds `app.include_router(sourcing.router)`

### Frontend

5. **`recruiter-frontend/src/components/kanban/search-tab.tsx`** (new)

   ```tsx
   interface Props {
     jobId: number;
     onAdded?: () => void;  // optional: parent decides whether to auto-close
   }
   ```

   Layout:
   - Three pill buttons (LinkedIn / GitHub / Web) using `<Button variant={selected ? "default" : "outline"} size="sm">` for selection state — no new shadcn primitive needed
   - `<Input>` for query, `placeholder="senior Rust engineer Berlin"`
   - `<Button onClick={search}>` with loading state
   - Error banner if `errors.length > 0` — small yellow box listing each failed source
   - Empty state: "No results found across selected sources." when both arrays empty after a search
   - Result stack: `results.map(r => <SearchResultCard result={r} jobId={jobId} />)`

   State:
   - `selected: Set<"linkedin" | "github" | "web">`
   - `query: string`
   - `results: SearchResult[]`
   - `errors: SearchErrorItem[]`
   - `useMutation` for the API call

   Search button disabled when `selected.size === 0` OR `query.trim() === ""`.

6. **`recruiter-frontend/src/components/kanban/add-candidate-panel.tsx`** (modify)

   - Adds a fourth `TabsTrigger value="search"` and matching `TabsContent`
   - `<SearchTab jobId={jobId} />` mounted inside

7. **`recruiter-frontend/src/components/applications/search-result-card.tsx`** (small enhancement)

   After a successful Add mutation, the button shows "Added ✓" and stays disabled. Local component state (`useState<boolean>(false)`); set true on `onSuccess`. Persists until card unmounts.

## Data flow

**Search round-trip:**

1. User opens `/jobs/5` → clicks **Add candidate** → clicks **Search** tab
2. Toggles LinkedIn + GitHub on, types `rust postgres berlin`, clicks **Search**
3. Frontend POSTs `/api/sourcing/search` with `{sources: ["linkedin", "github"], query: "rust postgres berlin", limit_per_source: 5}`
4. Backend loads SettingsRow, fans out via `asyncio.gather`:
   - LinkedIn task → `search_one_source("linkedin", ...)` → query becomes `site:linkedin.com/in/ rust postgres berlin` → Google CSE returns 5 results, source="linkedin"
   - GitHub task → `search_one_source("github", ...)` → GitHubSearchClient returns 5 results, source="github"
5. Backend returns `{results: [10 cards], errors: []}`
6. Frontend renders 10 `SearchResultCard`s

**Add round-trip:**

7. User clicks **Add** on a `https://github.com/spencerbart` card → existing SearchResultCard mutation POSTs `/api/jobs/5/candidates` with `{kind: "url", url}`
8. Backend creates Candidate + Application in `extracting`; classifier sees `github.com` → existing GitHub fetcher → LLM extraction → app advances to **Scored** automatically
9. Toast "Added to pipeline"; the card's button flips to "Added ✓" disabled; slide-over stays open for more adds

**Partial failure:**

If LinkedIn config is missing but GitHub works:

```json
{
  "results": [5 GitHub cards],
  "errors": [{"source": "linkedin", "reason": "Search isn't configured.", "transient": false}]
}
```

Frontend renders the GitHub cards normally + a yellow banner above: *"LinkedIn: Search isn't configured. Configure it in Settings → Sourcing."*

## Error handling

**Backend:**
- 422 (Pydantic): empty `sources`, empty `query`, `limit_per_source` out of [1, 30]
- Per-source errors caught in gather, mapped to `errors[]` with `transient` flag preserved from `SearchError`
- Unexpected (non-`SearchError`) exception → `errors[]` entry with `transient: true`, `reason: "internal error: <Class>"`. No stacktrace leak.
- Endpoint never returns 5xx for partial-source failures — that's reflected in `errors[]`. 5xx only for genuine server failure (DB down, etc.)
- Logging: INFO `sources, total_result_count, latency_ms`. Query text NOT logged. Errors at WARN.

**Frontend:**
- API call failure (network, 401, 5xx) → toast with `ApiError.detail`; previous results retained
- Per-source errors → yellow warning banner listing each
- Empty `results[]` + empty `errors[]` → friendly "No results found across selected sources."
- Add failure → existing `SearchResultCard` toast pattern (unchanged from Plan F)

## Testing

**Backend unit:**
- `tests/unit/test_sourcing_search.py` — `search_one_source`:
  - LinkedIn: prefix added, calls provider
  - Web: raw query, calls provider
  - GitHub: uses `GitHubSearchClient`, doesn't touch provider registry
  - source override per call
  - Settings unset → raises `SearchError(transient=False)`
  - Provider raises → propagates

**Backend integration:**
- `tests/api/test_sourcing_api.py`:
  - 200 happy path multi-source (stub provider + stub github via monkeypatch)
  - 200 partial failure (LinkedIn raises, GitHub succeeds → both reflected)
  - 200 all errored (results=[], errors has all)
  - 422 empty sources, 422 empty query, 422 limit out of range
- `tests/api/test_gating_sweep.py` — add `("POST", "/api/sourcing/search", {...minimal valid body})` so 401 is asserted unauthenticated

**Frontend:**
- `search-tab.test.tsx`:
  - Toggling source pills changes visual state
  - Search disabled until ≥1 source AND non-empty query
  - Submit posts correct body
  - Renders cards from response
  - Renders error banner when `errors[]` non-empty
  - Renders "No results found" empty state
  - Loading: button shows "Searching…"
- `search-result-card.test.tsx` — extend with: after Add success, button text becomes "Added ✓" and stays disabled

## Open questions

None blocking. The "Added ✓" state and the auto-close behavior were deliberately specified above; revisit if user testing shows the slide-over staying open is annoying.
