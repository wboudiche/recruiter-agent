# Add-Candidate Search (Plan G) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Search" tab to the Add Candidate slide-over with multi-source (LinkedIn / GitHub / Web) search, backed by a new `POST /api/sourcing/search` endpoint that runs sources concurrently with per-source error reporting.

**Architecture:** Extract the per-source search logic from Plan F's `agent/tools.py` into a shared `sourcing/search.py` module. Both the chat tools (Plan F) and the new HTTP endpoint (Plan G) call into it. Frontend reuses Plan F's `SearchResultCard` component; results are component-local state in the new tab. The new endpoint runs `asyncio.gather(return_exceptions=True)` so partial failures don't block other sources.

**Tech Stack:** Python 3.12 + FastAPI + SQLAlchemy 2.0 + httpx (backend); React 18 + Vite + TanStack Query v5 + msw + vitest (frontend).

---

## Task 1: Extract `search_one_source` into `sourcing/search.py`

**Files:**
- Create: `src/recruiter/sourcing/search.py`
- Create: `tests/unit/test_sourcing_search.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_sourcing_search.py`:

```python
import pytest

from recruiter.sourcing.provider import SearchError, SearchResult
from recruiter.sourcing.search import search_one_source


class _FakeProvider:
    def __init__(self, results=None, raises=None) -> None:
        self._results = results or []
        self._raises = raises
        self.last_query: str | None = None

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        self.last_query = query
        if self._raises:
            raise self._raises
        return self._results


@pytest.fixture
def fake_settings():
    return type("S", (), {
        "search_provider": "google_cse",
        "search_api_key_enc": b"x",
        "search_engine_id": "cx",
        "github_token_enc": None,
    })()


@pytest.mark.asyncio
async def test_search_linkedin_prepends_site_operator(fake_settings, monkeypatch) -> None:
    fake = _FakeProvider(results=[
        SearchResult(name="Alice", url="https://www.linkedin.com/in/alice/",
                     snippet="bio", source="web"),
    ])
    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _s: fake)

    out = await search_one_source(
        "linkedin", "rust postgres", 5, settings=fake_settings,
    )
    assert fake.last_query == "site:linkedin.com/in/ rust postgres"
    assert out[0].source == "linkedin"  # overridden from "web"


@pytest.mark.asyncio
async def test_search_web_passes_query_verbatim(fake_settings, monkeypatch) -> None:
    fake = _FakeProvider(results=[
        SearchResult(name="x", url="https://x", snippet="y", source="web"),
    ])
    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _s: fake)

    out = await search_one_source(
        "web", "remote python staff engineer", 5, settings=fake_settings,
    )
    assert fake.last_query == "remote python staff engineer"
    assert out[0].source == "web"


@pytest.mark.asyncio
async def test_search_github_uses_client_not_registry(
    fake_settings, monkeypatch,
) -> None:
    captured: dict = {}

    class _FakeGH:
        def __init__(self, *, token, transport=None) -> None:
            captured["token"] = token

        async def search_users(self, q, limit):
            return [SearchResult(name="alice", url="https://github.com/alice",
                                 snippet="x", source="github")]

        async def aclose(self): pass

    import recruiter.sourcing.search as search_mod
    monkeypatch.setattr(search_mod, "GitHubSearchClient", _FakeGH)

    out = await search_one_source(
        "github", "rust", 5, settings=fake_settings,  # github_token_enc=None
    )
    assert captured["token"] is None
    assert out[0].source == "github"


@pytest.mark.asyncio
async def test_search_raises_when_settings_unset() -> None:
    with pytest.raises(SearchError) as ei:
        await search_one_source("linkedin", "x", 5, settings=None)
    assert ei.value.transient is False


@pytest.mark.asyncio
async def test_search_raises_when_provider_unconfigured(
    fake_settings, monkeypatch,
) -> None:
    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _s: None)
    with pytest.raises(SearchError) as ei:
        await search_one_source("linkedin", "x", 5, settings=fake_settings)
    assert ei.value.transient is False


@pytest.mark.asyncio
async def test_search_propagates_provider_error(
    fake_settings, monkeypatch,
) -> None:
    fake = _FakeProvider(raises=SearchError("rate limit", transient=True))
    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _s: fake)
    with pytest.raises(SearchError) as ei:
        await search_one_source("web", "x", 5, settings=fake_settings)
    assert ei.value.transient is True
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/pytest tests/unit/test_sourcing_search.py -v`
Expected: collection error — module doesn't exist.

- [ ] **Step 3: Implement**

Create `src/recruiter/sourcing/search.py`:

```python
from typing import Literal

from recruiter.crypto import settings_cipher
from recruiter.models import SettingsRow
from recruiter.sourcing import provider as sourcing_provider
from recruiter.sourcing.github import GitHubSearchClient
from recruiter.sourcing.provider import SearchError, SearchResult


async def search_one_source(
    source: Literal["linkedin", "github", "web"],
    query: str,
    limit: int,
    *,
    settings: SettingsRow | None,
) -> list[SearchResult]:
    """Run a single search against the chosen source.

    Single source of truth shared by the chat tools (agent/tools.py) and
    the multi-source HTTP endpoint (api/sourcing.py). Callers handle
    LLM-context summary, frontend events, and error mapping; this just
    returns the raw cards or raises SearchError.

    LinkedIn: prepends `site:linkedin.com/in/` to the query and dispatches
    to the configured provider.
    Web: passes the query verbatim to the provider.
    GitHub: uses GitHubSearchClient directly (provider registry is
    LinkedIn/Web-only).

    Always overrides `SearchResult.source` to match the requested source.
    """
    if settings is None:
        raise SearchError(
            "Search isn't configured. Set a provider in Settings → Sourcing.",
            transient=False,
        )

    if source == "github":
        token = None
        if settings.github_token_enc:
            token = settings_cipher().decrypt(settings.github_token_enc)
        client = GitHubSearchClient(token=token)
        try:
            results = await client.search_users(query, limit)
        finally:
            await client.aclose()
        for r in results:
            r.source = "github"
        return results

    # linkedin / web go through the provider registry
    provider = sourcing_provider.resolve(settings)
    if provider is None:
        raise SearchError(
            "Search isn't configured. Set a provider in Settings → Sourcing.",
            transient=False,
        )

    if source == "linkedin":
        full_query = f"site:linkedin.com/in/ {query}"
    else:  # web
        full_query = query

    results = await provider.search(full_query, limit)
    for r in results:
        r.source = source
    return results
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/pytest tests/unit/test_sourcing_search.py -v`
Expected: 6 PASS.

Run: `.venv/bin/pytest -q`
Expected: full suite still green at 245 passed (was 239, +6 new).

Run: `.venv/bin/mypy src/recruiter`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/sourcing/search.py tests/unit/test_sourcing_search.py
git commit -m "feat(sourcing): extract search_one_source for shared use across tools + api"
```

---

## Task 2: Refactor `agent/tools.py` to use `search_one_source`

**Files:**
- Modify: `src/recruiter/agent/tools.py`
- Modify: `tests/unit/test_sourcing_tools.py`

This is a refactor — same external behavior, less code. The chat tool wrappers retain ToolContext concerns (frontend_events, summary text) but delegate the actual search dispatch to `search_one_source`.

- [ ] **Step 1: Update imports**

Edit `src/recruiter/agent/tools.py`. Replace the existing imports block additions (`GitHubSearchClient`, `SearchError`, `SearchResult`, `sourcing_provider`, `settings_cipher`) — keep what we still need:

Find:
```python
from typing import Literal

from recruiter.crypto import settings_cipher
from recruiter.models import Application, Candidate, Job, Stage, SettingsRow
from recruiter.sourcing import provider as sourcing_provider
from recruiter.sourcing.github import GitHubSearchClient
from recruiter.sourcing.provider import SearchError, SearchResult
from recruiter.agent.events import tool_search_results_event
```

Replace with:
```python
from typing import Literal

from recruiter.models import Application, Candidate, Job, Stage, SettingsRow
from recruiter.sourcing.provider import SearchError, SearchResult
from recruiter.sourcing.search import search_one_source
from recruiter.agent.events import tool_search_results_event
```

(Drop `settings_cipher`, `sourcing_provider`, `GitHubSearchClient` imports — not needed at this layer anymore.)

- [ ] **Step 2: Drop now-unused helpers**

In `src/recruiter/agent/tools.py`, delete the `_decrypt_github_token` function (no longer needed — `search_one_source` handles GitHub token decryption internally).

- [ ] **Step 3: Replace `_run_provider_search`**

Find and replace `_run_provider_search`:

```python
async def _run_provider_search(
    ctx: "ToolContext",
    *,
    query: str,
    limit: int,
    source: Literal["linkedin", "github", "web"],
    tool_name: str,
) -> dict:
    settings = await _load_settings_for_tool(ctx.session)
    try:
        results = await search_one_source(source, query, limit, settings=settings)
    except SearchError as e:
        if e.transient:
            return {"summary": f"Search temporarily unavailable: {e}."}
        return {"summary": f"{e}"}
    cards = [{"name": r.name, "url": r.url, "snippet": r.snippet, "source": r.source}
             for r in results]
    if cards:
        ctx.frontend_events.append(tool_search_results_event(
            tool_name=tool_name, source=source, results=cards,
        ))
    return {"summary": _format_results_for_llm(results)}
```

Key behavioral preservation:
- Settings unset OR provider unset → `SearchError(transient=False)` from `search_one_source` → returns `{"summary": "Search isn't configured. Set a provider in Settings → Sourcing."}` (the message text comes from `SearchError`).
- Transient errors → `"Search temporarily unavailable: ..."`
- Non-transient errors (other than not-configured) → use the error's own text via `f"{e}"`.

- [ ] **Step 4: Replace `_search_github`**

Find the `@_register("search_github")` block and replace with:

```python
@_register("search_github")
async def _search_github(ctx: "ToolContext", args: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"summary": "query is required"}
    limit = max(1, min(int(args.get("limit") or 5), 30))
    return await _run_provider_search(
        ctx, query=query, limit=limit, source="github", tool_name="search_github",
    )
```

The `_run_provider_search` already dispatches GitHub via `search_one_source`, so this becomes a thin wrapper just like LinkedIn and Web.

- [ ] **Step 5: Update existing chat-tools tests**

Edit `tests/unit/test_sourcing_tools.py`. The existing tests monkeypatch `recruiter.sourcing.provider.resolve` — that path is still valid because `search_one_source` calls `sourcing_provider.resolve()`. ✅

The GitHub test monkeypatches `recruiter.agent.tools.GitHubSearchClient`, but we removed that import. The test needs to patch the new location:

Find this block in `test_search_github_uses_github_client_not_provider`:
```python
    import recruiter.agent.tools as tools_mod
    async def _load_settings(_session): return fake_settings  # github_token_enc=None
    monkeypatch.setattr(tools_mod, "_load_settings_for_tool", _load_settings)
    monkeypatch.setattr(tools_mod, "GitHubSearchClient", _FakeGH)
```

Replace with:
```python
    import recruiter.agent.tools as tools_mod
    import recruiter.sourcing.search as search_mod
    async def _load_settings(_session): return fake_settings  # github_token_enc=None
    monkeypatch.setattr(tools_mod, "_load_settings_for_tool", _load_settings)
    monkeypatch.setattr(search_mod, "GitHubSearchClient", _FakeGH)
```

- [ ] **Step 6: Run, verify pass**

Run: `.venv/bin/pytest tests/unit/test_sourcing_tools.py tests/unit/test_sourcing_search.py tests/api/test_chat_search_tool.py -v`
Expected: all PASS — chat tool behavior preserved, search abstraction tested, integration test still passes.

Run: `.venv/bin/pytest -q`
Expected: 245 passed (no new tests, no removed tests).

Run: `.venv/bin/mypy src/recruiter`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/recruiter/agent/tools.py tests/unit/test_sourcing_tools.py
git commit -m "refactor(agent): chat tools delegate to sourcing.search.search_one_source"
```

---

## Task 3: New `POST /api/sourcing/search` endpoint

**Files:**
- Create: `src/recruiter/api/sourcing.py`
- Create: `tests/api/test_sourcing_api.py`
- Modify: `src/recruiter/main.py`
- Modify: `tests/api/test_gating_sweep.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_sourcing_api.py`:

```python
import pytest
from httpx import AsyncClient

from recruiter.sourcing.provider import SearchError, SearchResult


class _FakeProvider:
    def __init__(self, *, results=None, raises=None) -> None:
        self._results = results or []
        self._raises = raises

    async def search(self, query, limit):
        if self._raises:
            raise self._raises
        return self._results


async def _seed_settings(api_client: AsyncClient) -> None:
    """Settings row must exist with search_provider=google_cse so the
    provider resolver returns non-None when monkeypatched."""
    await api_client.put("/api/settings", json={
        "search_provider": "google_cse",
        "search_api_key": "x",
        "search_engine_id": "cx",
    })


@pytest.mark.asyncio
async def test_multi_source_happy_path(api_client: AsyncClient, monkeypatch) -> None:
    await _seed_settings(api_client)
    fake = _FakeProvider(results=[
        SearchResult(name="Alice", url="https://www.linkedin.com/in/alice/",
                     snippet="bio", source="web"),
    ])
    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _s: fake)

    class _FakeGH:
        def __init__(self, *, token, transport=None): pass
        async def search_users(self, q, limit):
            return [SearchResult(name="bob", url="https://github.com/bob",
                                 snippet="x", source="github")]
        async def aclose(self): pass

    import recruiter.sourcing.search as search_mod
    monkeypatch.setattr(search_mod, "GitHubSearchClient", _FakeGH)

    r = await api_client.post("/api/sourcing/search", json={
        "sources": ["linkedin", "github"],
        "query": "rust",
        "limit_per_source": 5,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["errors"] == []
    sources_in_results = {x["source"] for x in body["results"]}
    assert sources_in_results == {"linkedin", "github"}
    # Per-card source override worked: provider returned source="web", we want "linkedin"
    li = next(x for x in body["results"] if x["source"] == "linkedin")
    assert li["name"] == "Alice"


@pytest.mark.asyncio
async def test_partial_failure_returns_both_results_and_errors(
    api_client: AsyncClient, monkeypatch,
) -> None:
    await _seed_settings(api_client)
    # LinkedIn raises, GitHub succeeds.
    fake_provider = _FakeProvider(raises=SearchError("config", transient=False))
    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _s: fake_provider)

    class _FakeGH:
        def __init__(self, *, token, transport=None): pass
        async def search_users(self, q, limit):
            return [SearchResult(name="bob", url="https://github.com/bob",
                                 snippet="x", source="github")]
        async def aclose(self): pass

    import recruiter.sourcing.search as search_mod
    monkeypatch.setattr(search_mod, "GitHubSearchClient", _FakeGH)

    r = await api_client.post("/api/sourcing/search", json={
        "sources": ["linkedin", "github"],
        "query": "rust",
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["source"] == "github"
    assert len(body["errors"]) == 1
    assert body["errors"][0]["source"] == "linkedin"
    assert body["errors"][0]["transient"] is False
    assert "config" in body["errors"][0]["reason"]


@pytest.mark.asyncio
async def test_all_errored(api_client: AsyncClient, monkeypatch) -> None:
    await _seed_settings(api_client)
    fake_provider = _FakeProvider(raises=SearchError("rate", transient=True))
    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _s: fake_provider)

    class _BrokenGH:
        def __init__(self, *, token, transport=None): pass
        async def search_users(self, q, limit):
            raise SearchError("github 5xx", transient=True)
        async def aclose(self): pass

    import recruiter.sourcing.search as search_mod
    monkeypatch.setattr(search_mod, "GitHubSearchClient", _BrokenGH)

    r = await api_client.post("/api/sourcing/search", json={
        "sources": ["linkedin", "web", "github"],
        "query": "rust",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["results"] == []
    assert {e["source"] for e in body["errors"]} == {"linkedin", "web", "github"}
    assert all(e["transient"] for e in body["errors"])


@pytest.mark.asyncio
async def test_422_empty_sources(api_client: AsyncClient) -> None:
    r = await api_client.post("/api/sourcing/search", json={
        "sources": [], "query": "rust",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_422_empty_query(api_client: AsyncClient) -> None:
    r = await api_client.post("/api/sourcing/search", json={
        "sources": ["github"], "query": "",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_422_limit_out_of_range(api_client: AsyncClient) -> None:
    r = await api_client.post("/api/sourcing/search", json={
        "sources": ["github"], "query": "rust", "limit_per_source": 100,
    })
    assert r.status_code == 422
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/pytest tests/api/test_sourcing_api.py -v`
Expected: all FAIL — endpoint doesn't exist (404).

- [ ] **Step 3: Implement the endpoint**

Create `src/recruiter/api/sourcing.py`:

```python
import asyncio
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.deps import get_session, require_user
from recruiter.models import SettingsRow
from recruiter.sourcing.provider import SearchError, SearchResult
from recruiter.sourcing.search import search_one_source


router = APIRouter(prefix="/api/sourcing", tags=["sourcing"], dependencies=[Depends(require_user)])


SourceLiteral = Literal["linkedin", "github", "web"]


class SearchRequest(BaseModel):
    sources: list[SourceLiteral] = Field(min_length=1)
    query: str = Field(min_length=1)
    limit_per_source: int = Field(default=5, ge=1, le=30)


class SearchResultOut(BaseModel):
    name: str
    url: str
    snippet: str
    source: str


class SearchErrorItem(BaseModel):
    source: str
    reason: str
    transient: bool


class SearchResponse(BaseModel):
    results: list[SearchResultOut]
    errors: list[SearchErrorItem]


def _to_out(r: SearchResult) -> SearchResultOut:
    return SearchResultOut(name=r.name, url=r.url, snippet=r.snippet, source=r.source)


@router.post("/search", response_model=SearchResponse)
async def search(
    payload: SearchRequest,
    session: AsyncSession = Depends(get_session),
) -> SearchResponse:
    settings = await session.get(SettingsRow, 1)

    async def run(source: SourceLiteral) -> tuple[SourceLiteral, list[SearchResult] | Exception]:
        try:
            res = await search_one_source(
                source, payload.query, payload.limit_per_source, settings=settings,
            )
            return source, res
        except Exception as exc:
            return source, exc

    outcomes = await asyncio.gather(*[run(s) for s in payload.sources])

    results: list[SearchResultOut] = []
    errors: list[SearchErrorItem] = []
    for source, outcome in outcomes:
        if isinstance(outcome, SearchError):
            errors.append(SearchErrorItem(
                source=source, reason=str(outcome), transient=outcome.transient,
            ))
        elif isinstance(outcome, Exception):
            errors.append(SearchErrorItem(
                source=source, reason=f"internal error: {type(outcome).__name__}", transient=True,
            ))
        else:
            results.extend(_to_out(r) for r in outcome)
    return SearchResponse(results=results, errors=errors)
```

- [ ] **Step 4: Mount the router**

Edit `src/recruiter/main.py`. Find the imports block:

```python
from recruiter.api import (
    applications, auth, candidates, chat, events, jobs, notifications, settings,
)
```

Add `sourcing`:
```python
from recruiter.api import (
    applications, auth, candidates, chat, events, jobs, notifications, settings, sourcing,
)
```

Find the `app.include_router(...)` block at the bottom and append:
```python
app.include_router(sourcing.router)
```

- [ ] **Step 5: Add to gating sweep**

Edit `tests/api/test_gating_sweep.py`. In the `GATED` list, append:
```python
    ("POST",  "/api/sourcing/search"),
```

- [ ] **Step 6: Run, verify pass**

Run: `.venv/bin/pytest tests/api/test_sourcing_api.py tests/api/test_gating_sweep.py -v`
Expected: all PASS.

Run: `.venv/bin/pytest -q`
Expected: full suite green at 252 passed (was 245, +6 sourcing api + 1 sweep entry = +7).

Run: `.venv/bin/mypy src/recruiter`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/recruiter/api/sourcing.py \
        src/recruiter/main.py \
        tests/api/test_sourcing_api.py \
        tests/api/test_gating_sweep.py
git commit -m "feat(api): POST /api/sourcing/search — multi-source concurrent fan-out"
```

---

## Task 4: SearchResultCard "Added ✓" persistent state

**Files:**
- Modify: `recruiter-frontend/src/components/applications/search-result-card.tsx`
- Modify: `recruiter-frontend/src/components/applications/search-result-card.test.tsx`

- [ ] **Step 1: Write the failing test**

Append to `recruiter-frontend/src/components/applications/search-result-card.test.tsx`:

```tsx
describe("SearchResultCard — added state", () => {
  it("button shows 'Added ✓' and stays disabled after a successful Add", async () => {
    server.use(
      http.post("http://localhost:8000/api/jobs/1/candidates", () =>
        HttpResponse.json({ application_id: 99 }, { status: 202 }),
      ),
    );
    const Wrapper = wrap();
    render(<Wrapper><SearchResultCard result={RESULT} jobId={1} /></Wrapper>);
    const btn = screen.getByRole("button", { name: /add/i });
    fireEvent.click(btn);
    await waitFor(() => {
      const after = screen.getByRole("button", { name: /added/i });
      expect(after).toBeDisabled();
      expect(after.textContent).toMatch(/added/i);
    });
  });
});
```

- [ ] **Step 2: Run, verify fail**

Run: `cd recruiter-frontend && npm run test -- src/components/applications/search-result-card.test.tsx`
Expected: target test fails — button still says "Add" after success.

- [ ] **Step 3: Implement**

Edit `recruiter-frontend/src/components/applications/search-result-card.tsx`. Replace the existing component body:

```tsx
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

export interface SearchResult {
  name: string;
  url: string;
  snippet: string;
  source: "linkedin" | "github" | "web";
}

interface Props {
  result: SearchResult;
  jobId: number;
}

const SOURCE_LABEL: Record<SearchResult["source"], string> = {
  linkedin: "LinkedIn",
  github: "GitHub",
  web: "Web",
};

export function SearchResultCard({ result, jobId }: Props) {
  const qc = useQueryClient();
  const [added, setAdded] = useState(false);
  const add = useMutation({
    mutationFn: () =>
      api(`/api/jobs/${jobId}/candidates`, {
        method: "POST",
        json: { kind: "url", url: result.url },
      }),
    onSuccess: () => {
      toast.success("Added to pipeline");
      qc.invalidateQueries({ queryKey: queryKeys.jobApplications(jobId) });
      setAdded(true);
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "Add failed");
    },
  });

  return (
    <div className="border rounded p-2 space-y-1 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-sm truncate">{result.name}</span>
        <span className="text-muted-foreground uppercase text-[10px] shrink-0">
          {SOURCE_LABEL[result.source]}
        </span>
      </div>
      <p className="text-muted-foreground line-clamp-2">{result.snippet}</p>
      <div className="flex items-center justify-between gap-2">
        <a
          href={result.url}
          target="_blank"
          rel="noreferrer"
          className="underline truncate min-w-0"
        >
          {result.url}
        </a>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => add.mutate()}
          disabled={add.isPending || added}
        >
          {added ? "Added ✓" : add.isPending ? "Adding…" : "Add"}
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run, verify pass**

Run: `cd recruiter-frontend && npm run test -- src/components/applications/search-result-card.test.tsx`
Expected: 3 PASS (2 existing + 1 new).

Run: `cd recruiter-frontend && npm run test`
Expected: full suite green at 33 (was 32, +1 new).

Run: `cd recruiter-frontend && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
cd /home/walidboudiche/recruiter-agent
git add recruiter-frontend/src/components/applications/search-result-card.tsx \
        recruiter-frontend/src/components/applications/search-result-card.test.tsx
git commit -m "feat(frontend): SearchResultCard 'Added ✓' persistent state"
```

---

## Task 5: SearchTab component (multi-source pills + query + results)

**Files:**
- Create: `recruiter-frontend/src/components/kanban/search-tab.tsx`
- Create: `recruiter-frontend/src/components/kanban/search-tab.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `recruiter-frontend/src/components/kanban/search-tab.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { SearchTab } from "./search-tab";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function wrap() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("SearchTab", () => {
  it("Search button is disabled until ≥1 source AND non-empty query", () => {
    const Wrapper = wrap();
    render(<Wrapper><SearchTab jobId={1} /></Wrapper>);
    const search = screen.getByRole("button", { name: /^search$/i });
    expect(search).toBeDisabled();

    // Pick a source.
    fireEvent.click(screen.getByRole("button", { name: /^github$/i }));
    expect(search).toBeDisabled();  // still no query

    // Type a query.
    fireEvent.change(screen.getByPlaceholderText(/senior rust/i), {
      target: { value: "rust" },
    });
    expect(search).not.toBeDisabled();
  });

  it("submits the right body and renders result cards", async () => {
    let received: unknown;
    server.use(
      http.post("http://localhost:8000/api/sourcing/search", async ({ request }) => {
        received = await request.json();
        return HttpResponse.json({
          results: [{
            name: "Alice", url: "https://github.com/alice",
            snippet: "Rust dev", source: "github",
          }],
          errors: [],
        });
      }),
    );
    const Wrapper = wrap();
    render(<Wrapper><SearchTab jobId={1} /></Wrapper>);
    fireEvent.click(screen.getByRole("button", { name: /^github$/i }));
    fireEvent.change(screen.getByPlaceholderText(/senior rust/i), {
      target: { value: "rust" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));

    await screen.findByText("Alice");
    expect(received).toEqual({
      sources: ["github"], query: "rust", limit_per_source: 5,
    });
  });

  it("renders an error banner when the response has errors", async () => {
    server.use(
      http.post("http://localhost:8000/api/sourcing/search", () =>
        HttpResponse.json({
          results: [],
          errors: [{ source: "linkedin", reason: "not configured", transient: false }],
        }),
      ),
    );
    const Wrapper = wrap();
    render(<Wrapper><SearchTab jobId={1} /></Wrapper>);
    fireEvent.click(screen.getByRole("button", { name: /^linkedin$/i }));
    fireEvent.change(screen.getByPlaceholderText(/senior rust/i), {
      target: { value: "rust" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));

    await screen.findByText(/linkedin/i);
    expect(screen.getByText(/not configured/i)).toBeInTheDocument();
  });

  it("renders 'No results found' empty state when both arrays are empty", async () => {
    server.use(
      http.post("http://localhost:8000/api/sourcing/search", () =>
        HttpResponse.json({ results: [], errors: [] }),
      ),
    );
    const Wrapper = wrap();
    render(<Wrapper><SearchTab jobId={1} /></Wrapper>);
    fireEvent.click(screen.getByRole("button", { name: /^web$/i }));
    fireEvent.change(screen.getByPlaceholderText(/senior rust/i), {
      target: { value: "zzznoresults" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));

    await screen.findByText(/no results found/i);
  });
});
```

- [ ] **Step 2: Run, verify fail**

Run: `cd recruiter-frontend && npm run test -- src/components/kanban/search-tab.test.tsx`
Expected: collection error — file doesn't exist.

- [ ] **Step 3: Implement**

Create `recruiter-frontend/src/components/kanban/search-tab.tsx`:

```tsx
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  SearchResultCard,
  type SearchResult,
} from "@/components/applications/search-result-card";
import { api, ApiError } from "@/lib/api";

type Source = "linkedin" | "github" | "web";

interface SearchErrorItem {
  source: string;
  reason: string;
  transient: boolean;
}

interface SearchResponse {
  results: SearchResult[];
  errors: SearchErrorItem[];
}

interface Props {
  jobId: number;
}

const SOURCES: Source[] = ["linkedin", "github", "web"];
const SOURCE_LABEL: Record<Source, string> = {
  linkedin: "LinkedIn",
  github: "GitHub",
  web: "Web",
};

export function SearchTab({ jobId }: Props) {
  const [selected, setSelected] = useState<Set<Source>>(new Set());
  const [query, setQuery] = useState("");
  const [hasSearched, setHasSearched] = useState(false);
  const search = useMutation({
    mutationFn: (body: { sources: Source[]; query: string; limit_per_source: number }) =>
      api<SearchResponse>("/api/sourcing/search", { method: "POST", json: body }),
    onSettled: () => setHasSearched(true),
  });

  function toggle(source: Source) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(source)) next.delete(source);
      else next.add(source);
      return next;
    });
  }

  function onSearch() {
    if (selected.size === 0 || !query.trim()) return;
    search.mutate({
      sources: [...selected],
      query: query.trim(),
      limit_per_source: 5,
    });
  }

  const data = search.data;
  const apiErr = search.error instanceof ApiError ? search.error.detail : null;

  return (
    <div className="space-y-3 mt-4">
      <div className="flex gap-2">
        {SOURCES.map((s) => (
          <Button
            key={s}
            type="button"
            size="sm"
            variant={selected.has(s) ? "default" : "outline"}
            onClick={() => toggle(s)}
          >
            {SOURCE_LABEL[s]}
          </Button>
        ))}
      </div>

      <Input
        placeholder="senior Rust engineer Berlin"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onSearch();
        }}
      />

      <Button
        onClick={onSearch}
        disabled={selected.size === 0 || !query.trim() || search.isPending}
      >
        {search.isPending ? "Searching…" : "Search"}
      </Button>

      {apiErr && (
        <p className="text-xs text-red-600 border border-red-300 rounded p-2 bg-red-50">
          {apiErr}
        </p>
      )}

      {data?.errors && data.errors.length > 0 && (
        <div className="border border-yellow-400 bg-yellow-50 rounded p-2 space-y-1 text-xs">
          {data.errors.map((e) => (
            <p key={e.source}>
              <span className="font-medium uppercase">{e.source}</span>: {e.reason}
            </p>
          ))}
        </div>
      )}

      {hasSearched && data && data.results.length === 0 && data.errors.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No results found across selected sources.
        </p>
      )}

      <div className="space-y-2">
        {data?.results.map((r) => (
          <SearchResultCard key={`${r.source}:${r.url}`} result={r} jobId={jobId} />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run, verify pass**

Run: `cd recruiter-frontend && npm run test -- src/components/kanban/search-tab.test.tsx`
Expected: 4 PASS.

Run: `cd recruiter-frontend && npm run test`
Expected: 37 (was 33, +4 new).

Run: `cd recruiter-frontend && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
cd /home/walidboudiche/recruiter-agent
git add recruiter-frontend/src/components/kanban/search-tab.tsx \
        recruiter-frontend/src/components/kanban/search-tab.test.tsx
git commit -m "feat(frontend): SearchTab — multi-source pills + query + results"
```

---

## Task 6: Mount SearchTab as a fourth tab in Add Candidate

**Files:**
- Modify: `recruiter-frontend/src/components/kanban/add-candidate-panel.tsx`

- [ ] **Step 1: Add the new tab trigger and content**

Edit `recruiter-frontend/src/components/kanban/add-candidate-panel.tsx`.

Find the imports block at the top — add:
```tsx
import { SearchTab } from "./search-tab";
```

Find the `useState<"url" | "upload" | "paste">` declaration. Replace with:
```tsx
const [tab, setTab] = useState<"url" | "upload" | "paste" | "search">("url");
```

Find the `<TabsList>` block and append a fourth trigger:
```tsx
<TabsList>
  <TabsTrigger value="url">URL</TabsTrigger>
  <TabsTrigger value="upload">Upload</TabsTrigger>
  <TabsTrigger value="paste">Paste</TabsTrigger>
  <TabsTrigger value="search">Search</TabsTrigger>
</TabsList>
```

Find the last `<TabsContent value="paste" ...>...</TabsContent>` block and **after** it (before the closing `</Tabs>`) add:
```tsx
<TabsContent value="search" className="space-y-2 mt-4">
  <SearchTab jobId={jobId} />
</TabsContent>
```

Find the bottom button block — likely a Submit button shared by URL / Upload / Paste tabs. The Search tab does NOT need this Submit button (each card has its own Add button). Wrap the existing submit Button in a conditional so it doesn't render when tab === "search":

Find the existing `<Button` near the bottom (look for `disabled={...}` referencing tab states). Wrap or guard it:

```tsx
{tab !== "search" && (
  <Button
    onClick={onSubmit}
    disabled={
      (tab === "url" && !url) ||
      (tab === "upload" && !file) ||
      (tab === "paste" && !content) ||
      submitJson.isPending ||
      submitUpload.isPending
    }
  >
    {submitJson.isPending || submitUpload.isPending ? "Submitting…" : "Add candidate"}
  </Button>
)}
```

(Match the existing button's disabled-condition shape; the key change is the `tab !== "search"` guard.)

- [ ] **Step 2: Run frontend tests + tsc**

Run: `cd recruiter-frontend && npm run test`
Expected: full suite green at 37 (no regression — existing add-candidate tests don't reference the search tab).

Run: `cd recruiter-frontend && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Manual smoke (optional but recommended)**

Open the running app, navigate to any job page, click **Add candidate** → verify a fourth **Search** tab appears next to URL/Upload/Paste. Click it, toggle GitHub, type `rust`, click Search. Cards should appear; clicking Add should toast "Added to pipeline" and the button should flip to "Added ✓".

- [ ] **Step 4: Commit**

```bash
git add recruiter-frontend/src/components/kanban/add-candidate-panel.tsx
git commit -m "feat(frontend): mount SearchTab as 4th tab in Add Candidate slide-over"
```

---

## Final verification

After all 6 tasks:

- [ ] Backend: `.venv/bin/pytest -q` → 252+ passed, mypy clean
- [ ] Frontend: `cd recruiter-frontend && npm run test` → 37+ passed, tsc clean
- [ ] Manual: Add Candidate slide-over has a fourth "Search" tab; multi-source search returns merged cards; Add creates applications on the current job; per-source errors render as a yellow banner.

## Known v1 limitations (per design)

- No de-duplication: clicking Add twice on the same card creates two applications on the job (same as Plan F's chat search).
- No saved searches / search history.
- No pagination beyond `limit_per_source` (max 30; Google CSE caps at 10 internally).
- Search results vanish when the slide-over closes — not persisted across sessions.
