# Brave Search + SearXNG sourcing providers — Design

**Date:** 2026-05-10
**Status:** Draft

## Problem

Sourcing currently supports only `google_cse` for LinkedIn/Web search. Google Custom Search JSON API requires a Cloud project with a billing account attached, even for the 100/day free tier. Users who can't or won't link a billing account have no working web/LinkedIn sourcing path. GitHub search already works without billing.

## Goal

Add two free, no-billing-required alternatives to `google_cse`:

- **Brave Search** — hosted API, free tier of 2000 queries/month, free key, no card.
- **SearXNG (self-hosted)** — user runs a local Docker instance; unlimited, no auth required.

The user picks one active provider in Settings → Sourcing. The Add Candidate dialog's LinkedIn and Web tabs use whichever is configured.

## Non-goals

- Multi-provider parallel use. The current "one active provider" model stays.
- Public SearXNG instances. Self-hosted only — public ones often disable JSON or rate-limit aggressively.
- "Test connection" button in Settings.
- SearXNG auth header (assumes trusted local network).
- Migration of existing google_cse users (their config keeps working unchanged).

## Architecture

Both providers slot into the existing pluggable registry in `src/recruiter/sourcing/provider.py` with no changes to that file's public API. Each provider:

- Lives in its own module under `src/recruiter/sourcing/`.
- Exports a class implementing `SearchProvider` (async `search(query, limit) -> list[SearchResult]`).
- Registers a factory via `@register("<name>")` that reads from a `SettingsRow` and instantiates the class.

Module map after the change:

```
src/recruiter/sourcing/
├── provider.py       (unchanged: registry + types + new shared LinkedIn name parser)
├── search.py         (unchanged)
├── google_cse.py     (refactored: imports shared name parser instead of local)
├── brave.py          (NEW)
├── searxng.py        (NEW)
├── github.py         (unchanged)
└── __init__.py       (adds two F401 imports for new modules)
```

The shared LinkedIn title parser (`"Alice Doe - Senior Rust | LinkedIn"` → `"Alice Doe"`) currently lives as `_parse_name` in `google_cse.py`. It is moved to `provider.py` as `parse_linkedin_name(title: str | None) -> str | None` and consumed by `google_cse.py` and `brave.py`. SearXNG calls it conditionally when a result URL is on `linkedin.com`.

## Data model

No schema changes. Reuse existing columns on `SettingsRow` with provider-specific semantics:

| Provider     | `search_api_key_enc` | `search_engine_id`        |
| ------------ | -------------------- | ------------------------- |
| `google_cse` | API key (encrypted)  | CSE CX (plaintext)        |
| `brave`      | API key (encrypted)  | (ignored)                 |
| `searxng`    | (ignored)            | base URL (plaintext)      |

`search_provider` becomes a 3-value field: `"google_cse" | "brave" | "searxng"`. Existing rows with `search_provider = "google_cse"` are unaffected.

The `SettingsRead` shape exposed to the frontend already includes `has_search_api_key` (bool) and `search_engine_id` (string). The frontend chooses which input fields to render based on the active `search_provider`. No new SettingsRead fields are required.

## Backend providers

### Brave (`src/recruiter/sourcing/brave.py`)

```python
@register("brave")
def _factory(settings) -> BraveSearchProvider:
    if not settings.search_api_key_enc:
        raise SearchError("brave requires search_api_key", transient=False)
    api_key = settings_cipher().decrypt(settings.search_api_key_enc)
    return BraveSearchProvider(api_key=api_key)
```

`BraveSearchProvider`:
- `endpoint = "https://api.search.brave.com/res/v1/web/search"`
- Headers: `Accept: application/json`, `X-Subscription-Token: <api_key>`.
- Params: `{"q": query, "count": clamp(limit, 1, 20)}`.
- Response shape: `{"web": {"results": [{"title", "url", "description"}, ...]}}`.
- Result mapping: `name = parse_linkedin_name(title) or title or url`, `url = url`, `snippet = description or ""`, `source = "web"` (overwritten by `search_one_source`).

Error mapping:
- `401`/`403` → `SearchError(<body excerpt>, transient=False)` (auth/quota).
- `429`/`5xx`/network → `transient=True`.
- other non-200 → `transient=False`.

### SearXNG (`src/recruiter/sourcing/searxng.py`)

```python
@register("searxng")
def _factory(settings) -> SearXNGProvider:
    base = settings.search_engine_id
    if not base or not base.startswith(("http://", "https://")):
        raise SearchError(
            "searxng requires search_engine_id to be set to the instance URL",
            transient=False,
        )
    return SearXNGProvider(base_url=base.rstrip("/"))
```

`SearXNGProvider`:
- `endpoint = f"{base_url}/search"`
- No auth headers.
- Params: `{"q": query, "format": "json", "safesearch": 0}`.
- Response shape: `{"results": [{"title", "url", "content"}, ...]}`.
- Result mapping: `name = parse_linkedin_name(title) if "linkedin.com" in url else (title or url)`, `snippet = content or ""`, slice to `limit`.

Error mapping:
- `httpx.ConnectError`/`httpx.ConnectTimeout` → `SearchError("can't reach SearXNG at <url>: <err>", transient=True)`.
- non-200 → `transient=False` with body excerpt.

## Frontend (`recruiter-frontend/src/components/settings/sourcing-tab.tsx`)

Provider dropdown gains two items:

```tsx
<SelectItem value="google_cse">Google Custom Search</SelectItem>
<SelectItem value="brave">Brave Search</SelectItem>
<SelectItem value="searxng">SearXNG (self-hosted)</SelectItem>
```

Field visibility derives from `effProvider`:

| Field           | google_cse | brave | searxng |
| --------------- | ---------- | ----- | ------- |
| API key         | yes        | yes   | no      |
| CSE ID (cx)     | yes        | no    | no      |
| Instance URL    | no         | no    | yes     |
| GitHub token    | yes        | yes   | yes     |

The "Instance URL" input is bound to the same `cseId` React state and persists to `search_engine_id` on save. Label and placeholder change per provider:

- google_cse: label `"CSE ID (cx)"`, placeholder `"abcd1234:efgh5678"`.
- searxng: label `"Instance URL"`, placeholder `"http://localhost:8080"`.

Help text per provider:

- google_cse: existing copy (cse.google.com link).
- brave: `Get a free key at https://brave.com/search/api/ (no card required, 2000 queries/month).`
- searxng: `Run SearXNG via Docker. Enable formats: [json] in your settings.yml.`

The save payload logic gets a small adjustment: `save()` filters its body by the active provider so a stale value typed under a previous provider can't leak. Specifically:

- If `effProvider !== "google_cse"` and `effProvider !== "brave"`, drop `search_api_key`.
- If `effProvider !== "google_cse"` and `effProvider !== "searxng"`, drop `search_engine_id`.

Switching provider in the dropdown also resets the local `apiKey` and `cseId` state so the inputs (when re-shown) start from the persisted server value, not whatever was typed under the previous provider.

## Error UX

The existing search dialog displays `SearchError.detail` in a yellow toast/banner (visible in current screenshots). All new error paths produce human-readable strings suitable for that surface, e.g.:

- `"brave requires search_api_key"` → user opens Settings.
- `"can't reach SearXNG at http://localhost:8080: Connection refused"` → user starts their Docker container.
- `"brave 401: …"` / `"brave 429"` → user fixes key or waits.

No new client-side handling required — the frontend already maps `SearchError` → toast.

## Testing

### Backend (`tests/test_sourcing.py` style)

For each new provider, add tests using `httpx.MockTransport` (existing pattern in `test_sourcing.py`):

- **Brave success**: mock 200 with two results, assert mapped `SearchResult`s, assert `X-Subscription-Token` header present.
- **Brave 401**: assert `SearchError(transient=False)`.
- **Brave 429**: assert `SearchError(transient=True)`.
- **Brave missing key**: factory raises `SearchError`.
- **SearXNG success**: mock 200 with three results (one linkedin.com URL), assert linkedin name parsing applied to that result and not the others.
- **SearXNG connection refused**: simulate via raising transport, assert `transient=True`.
- **SearXNG missing/invalid URL**: factory raises `SearchError` for empty and non-http values.
- **Registry**: `provider.resolve(settings_with("brave"))` returns `BraveSearchProvider`; same for `searxng`.

### Frontend (`recruiter-frontend/test/sourcing-tab.test.tsx` style)

- Switching provider to Brave hides the CSE ID field; Save sends only `search_provider` + `search_api_key`.
- Switching provider to SearXNG hides the API key field; Save sends `search_provider` + `search_engine_id`.
- Switching back to google_cse re-shows both fields and preserves the persisted CX from server state.
- Typing an API key while `brave` is selected, then switching to `searxng` and saving, must NOT include `search_api_key` in the request body.

## Documentation

Append a short section to `docs/setup.md` titled "Sourcing providers" listing the three options with one-paragraph setup notes each (Brave key URL, SearXNG docker one-liner). Keep it tight — full setup walkthrough lives outside the repo.

## Rollout

Single PR. No migration. Existing `google_cse` users see two new dropdown options and otherwise unchanged behavior.

## Risks and mitigations

- **Brave free tier exhausted**: error message ("brave 429") points user to upgrade or switch. No silent fallback between providers — keep the model simple.
- **SearXNG instance returns HTML instead of JSON** (forgot the `[json]` formats config): a 200 with non-JSON body will surface as a JSON parse error. Wrap the parse in try/except and raise `SearchError("searxng returned non-JSON; enable formats: [json] in settings.yml", transient=False)`.
- **Schema column name lies**: `search_engine_id` holding a URL for SearXNG is mildly confusing for anyone reading the DB. Acceptable trade-off for zero migration. If a third URL-based provider gets added later, revisit Approach B (JSON config column).
