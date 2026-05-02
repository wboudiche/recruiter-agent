# Candidate Search (Plan F) — Design

**Author:** walid + claude
**Date:** 2026-05-02
**Status:** approved, ready for implementation plan

## Goal

Let the recruiter find candidates from the open web by asking the existing chat agent in natural language (e.g. *"find me 5 senior Rust engineers in Berlin"*). Results render as cards inside the chat panel; clicking "Add" on a card creates an application that funnels into the existing extraction pipeline.

## Scope

### In scope (v1)

- Three search tools added to the chat agent:
  - `search_linkedin(query, limit)`
  - `search_github(query, limit)`
  - `search_web(query, limit)`
- A pluggable provider abstraction for the Google-backed tools (LinkedIn + general web). One concrete provider — **Google Custom Search Engine (CSE)** — ships in v1.
- A separate GitHub client using GitHub's own REST API.
- Result cards rendered in the chat panel with an "Add" button that POSTs to the existing `POST /api/jobs/{job_id}/candidates`.
- Settings UI section to configure provider, API key, CSE ID, and optional GitHub token.

### Out of scope (deferred)

- SerpAPI / Brave / Tavily implementations (provider abstraction leaves slots; concrete classes deferred until a user actually wants to swap).
- Real LinkedIn scraping (against ToS — LinkedIn results funnel through the existing manual-paste UX).
- Salary / seniority filters beyond what the search snippet already shows.
- De-duplication against existing pipeline candidates (clicking "Add" on someone already in the job creates a duplicate row; document as known limitation).
- Autonomous background sourcing (no agent searches without the recruiter asking).
- A separate cost cap for search queries (existing `monthly_llm_spend_cap_usd` doesn't apply; revisit if usage grows).
- "Test connection" button in Settings.

## Architecture

```
┌─────────────────┐   chat NDJSON stream   ┌─────────────────────┐
│  ChatPanel UI   │ ◄────────────────────► │ /api/applications/  │
│                 │                        │  {id}/chat          │
│ ┌─────────────┐ │                        │                     │
│ │ result card │ │   POST /candidates     │  agent.run_turn()   │
│ │ + Add btn   │─┼────────────────────►   │                     │
│ └─────────────┘ │                        └──────────┬──────────┘
└─────────────────┘                                   │
                                                      ▼
                                  ┌──────────────────────────────────┐
                                  │ agent/tools.py                   │
                                  │  search_linkedin / _github / _web│
                                  └──────────┬───────────────────────┘
                                             │
                          ┌──────────────────┴──────────────────┐
                          ▼                                     ▼
                ┌──────────────────┐                  ┌──────────────────┐
                │ sourcing/        │                  │ sourcing/        │
                │ provider.py      │                  │ github.py        │
                │ (registry)       │                  │ (REST direct)    │
                └────────┬─────────┘                  └──────────────────┘
                         │
                         ▼
              ┌────────────────────┐
              │ google_cse.py      │
              │ (v1 default)       │
              └────────────────────┘
```

The chat agent gains three tools. Two of them (LinkedIn, web) go through a provider abstraction; the third (GitHub) talks to GitHub's API directly because GitHub doesn't fit the same model.

When the user clicks "Add" on a result card, the frontend POSTs to the existing candidate-creation endpoint with `{kind: "url", url}`. The backend's URL classifier then routes:

- **LinkedIn URL** → application created in `extracting`, `awaiting_paste` flips true → kanban card shows yellow border + "Needs profile" badge → user pastes content via the just-shipped paste form
- **GitHub URL** → existing GitHub fetcher pulls README + pinned repos → app advances to `scored` automatically
- **Generic webpage URL** → existing webpage fetcher runs → app advances to `scored`

No new candidate-creation endpoint, no new pipeline stage.

## Components

### Backend

```
src/recruiter/sourcing/
├── __init__.py
├── provider.py     # SearchProvider Protocol + SearchResult + registry
├── google_cse.py   # default v1 implementation
└── github.py       # standalone GitHub REST client
```

**`provider.py`**
- `SearchResult` dataclass: `name: str`, `url: str`, `snippet: str`, `source: Literal["linkedin", "github", "web"]`
- `SearchError(Exception)` — base for provider failures, with `transient: bool` attribute so the tool handler can format the user-facing message.
- `class SearchProvider(Protocol)`: `async def search(self, query: str, limit: int) -> list[SearchResult]`
- Module-level registry: `_providers: dict[str, Callable[[SettingsRow], SearchProvider]]`. A `register(name)` decorator; `resolve(settings: SettingsRow) -> SearchProvider | None` looks up the configured provider.

**`google_cse.py`**
- `class GoogleCSEProvider`: takes `api_key: str` + `cse_id: str`. Uses module-level `httpx.AsyncClient` (or constructed per-call; matches existing pattern in `auth/oidc.py`).
- `search()` calls `GET https://www.googleapis.com/customsearch/v1?key={k}&cx={c}&q={q}&num={n}`. Maps `items[]` → `SearchResult`. Title is parsed (split on " - " or " | " to extract person name; LinkedIn titles are typically `"Name - Title - Company | LinkedIn"`).
- Status mapping:
  - 200 → results
  - 401 / 403 → `SearchError(transient=False)` ("Check your API key / CSE ID")
  - 429 → `SearchError(transient=True)` ("Rate limit, try again later")
  - 5xx / network → `SearchError(transient=True)`

**`github.py`**
- `class GitHubSearchClient`: takes optional `token: str | None`. Uses `Authorization: Bearer ...` header when present (raises rate limit from 60/hr to 5000/hr).
- `search_users(query: str, limit: int) -> list[SearchResult]` calls `GET https://api.github.com/search/users?q={q}&per_page={n}`. Maps response items: `name = login`, `url = html_url`, `snippet = ""` (login + repo count, can enrich in v2).
- Same `SearchError` exception shape so tool handlers treat it uniformly.

**`agent/tools.py` additions** — three new tool definitions following the existing `ToolContext` pattern:
- Each accepts `query: str` and `limit: int = 5` (clamped server-side to `[1, 20]`).
- Each returns a `(text_for_llm: str, structured_event: dict)` tuple. The agent loop emits the structured event as `tool.search_results` and feeds the text back into the LLM context.
- On `SearchError`: tool returns `("Search temporarily unavailable: {reason}", None)` (transient) or `("Search isn't configured correctly: {reason}. Set it in Settings → Sourcing.", None)` (config). On provider not configured: `("Search isn't configured. Set a provider in Settings → Sourcing.", None)`.

**`agent/events.py` addition** — new event type `tool.search_results` with payload `{tool_name, source, results: [SearchResult, ...]}`.

### Settings

**`models/settings.py` + Alembic migration** — four new columns on the singleton row:
- `search_provider: str | None` (e.g. `"google_cse"`)
- `search_api_key_enc: bytes | None` (encrypted via `SecretCipher`)
- `search_engine_id: str | None` (plain text; CSE ID is not sensitive)
- `github_token_enc: bytes | None` (encrypted, optional — GitHub works without it but at lower rate limit)

**`schemas/settings.py`** — extend `SettingsRead` (`has_search_api_key: bool`, `search_provider`, `search_engine_id`, `has_github_token: bool`) and `SettingsUpdate` (the four set-once fields).

### Frontend

**`recruiter-frontend/src/components/applications/search-result-card.tsx`** — new component. Props: `result: {name, url, snippet, source}`, `jobId: number`. Renders:
- Source icon (LinkedIn / GitHub / web glyph)
- Name (bold) + snippet (small text)
- URL (clickable, opens in new tab)
- "Add" button → calls `useMutation` posting to `/api/jobs/${jobId}/candidates` with `{kind: "url", url}`. On success: toast `"Added to pipeline"` + invalidate `queryKeys.jobApplications(jobId)`. On error: toast with `ApiError.detail`.

**`chat-panel.tsx`** — handle `tool.search_results` event. When received, append a vertical stack of `SearchResultCard` components inside the assistant's message bubble.

**Settings page** — new "Sourcing" section (or tab, matching the existing LLM/Notifications pattern). Inputs:
- Provider dropdown (v1 contains only `google_cse` and a disabled "More coming soon" option)
- API key input (write-only, masked indicator if set)
- CSE ID input (plain text)
- GitHub token input (write-only, masked indicator if set)
- Save button — same PUT /api/settings flow as other tabs.

## Data flow

**Search round-trip:**

1. User chats *"find me 5 senior Rust engineers in Berlin"* on `/applications/{id}`.
2. `POST /api/applications/{id}/chat` streams NDJSON. Agent loop decides to call `search_linkedin(query="senior Rust engineers Berlin", limit=5)`.
3. Tool handler loads Settings, resolves provider via `provider.resolve()`, instantiates `GoogleCSEProvider(api_key, cse_id)`.
4. Provider calls Google CSE with `q = "site:linkedin.com/in/ senior Rust engineers Berlin"`.
5. Tool handler emits a `tool.search_results` event on the stream and returns text-summary to the LLM.
6. LLM continues — may comment, may chain another search call (bounded by existing per-turn tool-call limit in `run_turn`).

**Add round-trip:**

7. User clicks "Add" on a card. Frontend POSTs `/api/jobs/${jobId}/candidates` with `{kind: "url", url}`.
8. Backend's URL classifier (existing `pipeline/router.py`) routes by host: linkedin → `awaiting_paste` flow; github → auto-fetch; webpage → auto-fetch.
9. Card appears in the kanban; the user follows the existing per-source extraction path.

## Error handling & observability

**Provider errors:** wrapped as `SearchError(transient: bool, message: str)` and converted by the tool handler into LLM-readable text. They never bubble into the chat stream as crashes.

**Logging:** at INFO, log `provider=..., source=..., query_length=..., result_count=..., latency_ms=...`. **Do not log the query text itself** — recruiters search for real names. At WARN log error class on failures, no PII.

**Frontend:** "Add" failure → toast with `ApiError.detail`. Existing pattern.

**Secrets:** API keys go through the existing `SecretCipher` (RECRUITER_SETTINGS_KEY). Same shape as the Anthropic key and SMTP credentials.

## Testing

**Backend unit:**
- `tests/unit/test_sourcing_provider.py` — registry returns the configured provider; returns `None` when unset.
- `tests/unit/test_google_cse.py` — `GoogleCSEProvider` against `httpx.MockTransport`: 200 happy path, 401 → `SearchError(transient=False)`, 429 → `SearchError(transient=True)`, empty `items[]` → empty list, malformed title fallback.
- `tests/unit/test_github_search.py` — same shape for `GitHubSearchClient`. With and without token.
- `tests/unit/test_sourcing_tools.py` — each of the three tool handlers against a fake provider: configured + has-results, configured + provider-raises, not-configured. Assert returned text and structured event shape.

**Backend integration:**
- `tests/api/test_chat_search_tool.py` — POST to `/api/applications/{id}/chat` with a stub LLM that returns a `tool_use` for `search_linkedin`. Backend calls a fake provider; NDJSON stream contains the `tool.search_results` event with the right structure. End-to-end through `run_turn`, no real LLM or Google.

**Frontend:**
- `search-result-card.test.tsx` — renders source/name/snippet/url; clicking "Add" hits the candidate-create endpoint and toasts on success.
- `chat-panel.test.tsx` (extension of existing tests) — receiving a `tool.search_results` event renders the card stack inline in the assistant's message.

## Open questions

None blocking implementation. Provider choice for v1 is locked to Google CSE; the abstraction makes swapping later painless.
