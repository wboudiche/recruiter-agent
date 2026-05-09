# Brave Search + SearXNG sourcing providers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Brave Search and self-hosted SearXNG as alternative providers to `google_cse` for the LinkedIn/Web sourcing pipeline, so users without a Google Cloud billing account have a working path.

**Architecture:** Two new modules under `src/recruiter/sourcing/` register themselves through the existing `@register(name)` factory system. Settings columns (`search_api_key_enc`, `search_engine_id`) are reused with provider-specific semantics — no schema migration. Frontend renders fields conditionally on the active provider.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.x async, httpx (with `MockTransport` for tests), pytest-asyncio. React 18, vitest, MSW, @testing-library/react, sonner toasts.

**Spec:** `docs/superpowers/specs/2026-05-10-brave-searxng-providers-design.md`

---

### Task 1: Extract shared LinkedIn name parser to `provider.py`

**Files:**
- Modify: `src/recruiter/sourcing/provider.py`
- Modify: `src/recruiter/sourcing/google_cse.py`
- Create: `tests/unit/test_provider_helpers.py`

**Why first:** Both Brave and SearXNG need the same LinkedIn title parsing. Pulling the helper up before adding new providers keeps DRY and avoids two copies of the regex logic.

- [ ] **Step 1: Write a failing test for `parse_linkedin_name`**

Create `tests/unit/test_provider_helpers.py`:

```python
import pytest

from recruiter.sourcing.provider import parse_linkedin_name


@pytest.mark.parametrize("title,expected", [
    ("Alice Doe - Senior Rust Engineer | LinkedIn", "Alice Doe"),
    ("Bob | LinkedIn", "Bob"),
    ("  Carol Smith  - VP", "Carol Smith"),
    ("Dan", "Dan"),
])
def test_parse_linkedin_name_extracts_name(title: str, expected: str) -> None:
    assert parse_linkedin_name(title) == expected


@pytest.mark.parametrize("title", [None, "", "   "])
def test_parse_linkedin_name_returns_none_for_empty(title) -> None:
    assert parse_linkedin_name(title) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_provider_helpers.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_linkedin_name'`.

- [ ] **Step 3: Move the helper into `provider.py`**

Append to `src/recruiter/sourcing/provider.py`:

```python
def parse_linkedin_name(title: str | None) -> str | None:
    """Extract a person's name from a LinkedIn search-result title.

    LinkedIn titles look like 'Alice Doe - Senior Rust | LinkedIn'.
    Strip the '| LinkedIn' suffix and take the segment before the first
    ' - '. Returns None if the title is empty or whitespace-only.
    """
    if not title or not title.strip():
        return None
    cleaned = title.split(" | ")[0].strip()
    return cleaned.split(" - ")[0].strip() or None
```

- [ ] **Step 4: Replace the local helper in `google_cse.py`**

In `src/recruiter/sourcing/google_cse.py`, delete the `_parse_name` function (lines 10-17) and update the import + call site:

```python
import httpx

from recruiter.crypto import settings_cipher
from recruiter.sourcing.provider import (
    SearchError,
    SearchResult,
    parse_linkedin_name,
    register,
)


GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"


class GoogleCSEProvider:
    """Google Custom Search Engine provider. Configure a CSE in cse.google.com,
    enable the Custom Search API in Google Cloud Console, and pass the API
    key + CX here."""

    def __init__(
        self,
        *,
        api_key: str,
        cse_id: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._cse_id = cse_id
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        params: dict[str, str | int] = {
            "key": self._api_key,
            "cx": self._cse_id,
            "q": query,
            "num": max(1, min(limit, 10)),  # CSE caps at 10 per call
        }
        try:
            r = await self._client.get(GOOGLE_CSE_URL, params=params)
        except httpx.HTTPError as e:
            raise SearchError(f"network failure: {e}", transient=True) from e
        if r.status_code in (401, 403):
            raise SearchError(f"google CSE auth: {r.text[:200]}", transient=False)
        if r.status_code == 429:
            raise SearchError("google CSE rate limit", transient=True)
        if r.status_code >= 500:
            raise SearchError(f"google CSE {r.status_code}", transient=True)
        if r.status_code != 200:
            raise SearchError(f"google CSE {r.status_code}: {r.text[:200]}", transient=False)
        items = r.json().get("items", []) or []
        out: list[SearchResult] = []
        for it in items:
            link = it.get("link", "")
            if not link:
                continue
            name = parse_linkedin_name(it.get("title")) or link
            out.append(SearchResult(
                name=name,
                url=link,
                snippet=it.get("snippet", "") or "",
                source="web",
            ))
        return out


@register("google_cse")
def _factory(settings) -> GoogleCSEProvider:
    if not settings.search_api_key_enc or not settings.search_engine_id:
        raise SearchError(
            "google_cse requires both search_api_key and search_engine_id",
            transient=False,
        )
    api_key = settings_cipher().decrypt(settings.search_api_key_enc)
    return GoogleCSEProvider(api_key=api_key, cse_id=settings.search_engine_id)
```

- [ ] **Step 5: Run all sourcing tests**

Run: `uv run pytest tests/unit/test_provider_helpers.py tests/unit/test_google_cse.py tests/unit/test_sourcing_provider.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/recruiter/sourcing/provider.py src/recruiter/sourcing/google_cse.py tests/unit/test_provider_helpers.py
git commit -m "refactor(sourcing): hoist parse_linkedin_name into provider.py"
```

---

### Task 2: Brave provider — failing tests

**Files:**
- Create: `tests/unit/test_brave.py`

- [ ] **Step 1: Write the test file**

Create `tests/unit/test_brave.py`:

```python
import httpx
import pytest

from recruiter.sourcing.brave import BraveSearchProvider
from recruiter.sourcing.provider import SearchError


def _make_provider(transport: httpx.MockTransport) -> BraveSearchProvider:
    return BraveSearchProvider(api_key="brv_test_key", transport=transport)


@pytest.mark.asyncio
async def test_search_returns_results_for_200() -> None:
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["host"] = req.url.host
        seen["path"] = req.url.path
        seen["token_header"] = req.headers.get("x-subscription-token")
        seen["accept"] = req.headers.get("accept")
        seen["q"] = req.url.params.get("q")
        return httpx.Response(200, json={
            "web": {
                "results": [
                    {
                        "title": "Alice Doe - Senior Rust Engineer | LinkedIn",
                        "url": "https://www.linkedin.com/in/alice/",
                        "description": "5 years Rust, async / Postgres.",
                    },
                    {
                        "title": "Bob | LinkedIn",
                        "url": "https://www.linkedin.com/in/bob/",
                        "description": "Backend engineer.",
                    },
                ],
            },
        })

    p = _make_provider(httpx.MockTransport(handler))
    results = await p.search("site:linkedin.com/in/ rust engineer", 5)
    assert seen["host"] == "api.search.brave.com"
    assert seen["path"] == "/res/v1/web/search"
    assert seen["token_header"] == "brv_test_key"
    assert seen["accept"] == "application/json"
    assert seen["q"] == "site:linkedin.com/in/ rust engineer"
    assert len(results) == 2
    assert results[0].name == "Alice Doe"
    assert results[0].url == "https://www.linkedin.com/in/alice/"
    assert "5 years Rust" in results[0].snippet
    assert results[0].source == "web"


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_results() -> None:
    handler = lambda req: httpx.Response(200, json={"web": {"results": []}})
    p = _make_provider(httpx.MockTransport(handler))
    assert await p.search("zzznoresults", 5) == []


@pytest.mark.asyncio
async def test_search_handles_missing_web_key() -> None:
    handler = lambda req: httpx.Response(200, json={})
    p = _make_provider(httpx.MockTransport(handler))
    assert await p.search("x", 5) == []


@pytest.mark.asyncio
async def test_search_raises_config_error_on_401() -> None:
    handler = lambda req: httpx.Response(401, text="bad key")
    p = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(SearchError) as ei:
        await p.search("x", 5)
    assert ei.value.transient is False


@pytest.mark.asyncio
async def test_search_raises_transient_error_on_429() -> None:
    handler = lambda req: httpx.Response(429, text="rate")
    p = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(SearchError) as ei:
        await p.search("x", 5)
    assert ei.value.transient is True


@pytest.mark.asyncio
async def test_search_raises_transient_error_on_5xx() -> None:
    handler = lambda req: httpx.Response(503, text="oops")
    p = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(SearchError) as ei:
        await p.search("x", 5)
    assert ei.value.transient is True


@pytest.mark.asyncio
async def test_search_falls_back_to_url_when_title_missing() -> None:
    handler = lambda req: httpx.Response(200, json={
        "web": {"results": [{"url": "https://example.com/", "description": "no title"}]},
    })
    p = _make_provider(httpx.MockTransport(handler))
    results = await p.search("x", 5)
    assert results[0].name == "https://example.com/"


@pytest.mark.asyncio
async def test_search_clamps_count_to_brave_max() -> None:
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["count"] = req.url.params.get("count")
        return httpx.Response(200, json={"web": {"results": []}})

    p = _make_provider(httpx.MockTransport(handler))
    await p.search("x", 999)
    assert seen["count"] == "20"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_brave.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'recruiter.sourcing.brave'`.

---

### Task 3: Brave provider — implementation

**Files:**
- Create: `src/recruiter/sourcing/brave.py`
- Modify: `src/recruiter/sourcing/__init__.py`

- [ ] **Step 1: Implement `BraveSearchProvider`**

Create `src/recruiter/sourcing/brave.py`:

```python
import httpx

from recruiter.crypto import settings_cipher
from recruiter.sourcing.provider import (
    SearchError,
    SearchResult,
    parse_linkedin_name,
    register,
)


BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveSearchProvider:
    """Brave Search API provider. Free tier of 2000 queries/month, no card.
    Get a key at https://brave.com/search/api/."""

    def __init__(
        self,
        *,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        params: dict[str, str | int] = {
            "q": query,
            "count": max(1, min(limit, 20)),  # Brave caps at 20 per call
        }
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self._api_key,
        }
        try:
            r = await self._client.get(BRAVE_SEARCH_URL, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise SearchError(f"network failure: {e}", transient=True) from e
        if r.status_code in (401, 403):
            raise SearchError(f"brave auth: {r.text[:200]}", transient=False)
        if r.status_code == 429:
            raise SearchError("brave rate limit", transient=True)
        if r.status_code >= 500:
            raise SearchError(f"brave {r.status_code}", transient=True)
        if r.status_code != 200:
            raise SearchError(f"brave {r.status_code}: {r.text[:200]}", transient=False)
        web = r.json().get("web") or {}
        items = web.get("results") or []
        out: list[SearchResult] = []
        for it in items:
            url = it.get("url", "")
            if not url:
                continue
            name = parse_linkedin_name(it.get("title")) or it.get("title") or url
            out.append(SearchResult(
                name=name,
                url=url,
                snippet=it.get("description", "") or "",
                source="web",
            ))
        return out


@register("brave")
def _factory(settings) -> BraveSearchProvider:
    if not settings.search_api_key_enc:
        raise SearchError("brave requires search_api_key", transient=False)
    api_key = settings_cipher().decrypt(settings.search_api_key_enc)
    return BraveSearchProvider(api_key=api_key)
```

- [ ] **Step 2: Wire the module into the registry import chain**

Modify `src/recruiter/sourcing/__init__.py`. The current file imports `google_cse` so its `@register` runs at app startup; add the same for `brave`:

```python
# noqa imports run the @register decorators in each provider module.
from recruiter.sourcing import google_cse as _google_cse  # noqa: F401
from recruiter.sourcing import brave as _brave  # noqa: F401
```

(Replace the existing single import line with both.)

- [ ] **Step 3: Run the Brave tests**

Run: `uv run pytest tests/unit/test_brave.py -v`
Expected: all 8 tests PASS.

- [ ] **Step 4: Add a registry resolution test**

Append to `tests/unit/test_brave.py`:

```python
def test_brave_registered_in_global_registry() -> None:
    # Importing recruiter.sourcing must register "brave" via __init__.
    import recruiter.sourcing  # noqa: F401  triggers the brave import
    from recruiter.sourcing.provider import resolve

    fake_settings = type("S", (), {
        "search_provider": "brave",
        # search_api_key_enc holds an encrypted blob; the factory will try
        # to decrypt it. Provide a real-looking encrypted value below.
    })()
    # The factory needs a real encrypted blob — simulate using settings_cipher.
    from recruiter.crypto import settings_cipher
    enc = settings_cipher().encrypt("brv_dummy")
    fake_settings.search_api_key_enc = enc
    p = resolve(fake_settings)
    assert isinstance(p, BraveSearchProvider)


def test_brave_factory_raises_when_key_missing() -> None:
    import recruiter.sourcing  # noqa: F401
    from recruiter.sourcing.provider import resolve

    fake_settings = type("S", (), {
        "search_provider": "brave",
        "search_api_key_enc": None,
    })()
    with pytest.raises(SearchError) as ei:
        resolve(fake_settings)
    assert ei.value.transient is False
```

- [ ] **Step 5: Run the full Brave test file**

Run: `uv run pytest tests/unit/test_brave.py -v`
Expected: all 10 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/recruiter/sourcing/brave.py src/recruiter/sourcing/__init__.py tests/unit/test_brave.py
git commit -m "feat(sourcing): add Brave Search provider"
```

---

### Task 4: SearXNG provider — failing tests

**Files:**
- Create: `tests/unit/test_searxng.py`

- [ ] **Step 1: Write the test file**

Create `tests/unit/test_searxng.py`:

```python
import httpx
import pytest

from recruiter.sourcing.provider import SearchError
from recruiter.sourcing.searxng import SearXNGProvider


def _make_provider(transport: httpx.MockTransport) -> SearXNGProvider:
    return SearXNGProvider(base_url="http://localhost:8080", transport=transport)


@pytest.mark.asyncio
async def test_search_hits_search_endpoint_with_json_format() -> None:
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["host"] = req.url.host
        seen["path"] = req.url.path
        seen["q"] = req.url.params.get("q")
        seen["format"] = req.url.params.get("format")
        return httpx.Response(200, json={"results": []})

    p = _make_provider(httpx.MockTransport(handler))
    await p.search("rust engineer", 5)
    assert seen["host"] == "localhost"
    assert seen["path"] == "/search"
    assert seen["q"] == "rust engineer"
    assert seen["format"] == "json"


@pytest.mark.asyncio
async def test_search_maps_results_and_parses_linkedin_titles() -> None:
    handler = lambda req: httpx.Response(200, json={
        "results": [
            {
                "title": "Alice Doe - Senior Rust | LinkedIn",
                "url": "https://www.linkedin.com/in/alice/",
                "content": "Async Rust + Postgres",
            },
            {
                "title": "Acme — Hiring Rust Engineers",
                "url": "https://acme.example/jobs",
                "content": "We hire Rust engineers",
            },
        ],
    })
    p = _make_provider(httpx.MockTransport(handler))
    results = await p.search("rust", 5)
    assert len(results) == 2
    # LinkedIn URL: name parsed from title.
    assert results[0].name == "Alice Doe"
    assert results[0].url == "https://www.linkedin.com/in/alice/"
    # Non-LinkedIn URL: title kept as-is.
    assert results[1].name == "Acme — Hiring Rust Engineers"
    assert results[1].source == "web"


@pytest.mark.asyncio
async def test_search_clamps_to_limit() -> None:
    handler = lambda req: httpx.Response(200, json={
        "results": [
            {"title": f"r{i}", "url": f"https://x/{i}", "content": ""}
            for i in range(10)
        ],
    })
    p = _make_provider(httpx.MockTransport(handler))
    results = await p.search("x", 3)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_search_raises_transient_on_connect_failure() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=req)

    p = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(SearchError) as ei:
        await p.search("x", 5)
    assert ei.value.transient is True
    assert "localhost:8080" in str(ei.value)


@pytest.mark.asyncio
async def test_search_raises_config_error_on_non_200() -> None:
    handler = lambda req: httpx.Response(403, text="forbidden")
    p = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(SearchError) as ei:
        await p.search("x", 5)
    assert ei.value.transient is False


@pytest.mark.asyncio
async def test_search_raises_when_response_is_not_json() -> None:
    handler = lambda req: httpx.Response(
        200, text="<!DOCTYPE html><html>...</html>",
        headers={"content-type": "text/html"},
    )
    p = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(SearchError) as ei:
        await p.search("x", 5)
    assert ei.value.transient is False
    assert "json" in str(ei.value).lower()


def test_factory_raises_when_url_missing() -> None:
    import recruiter.sourcing  # noqa: F401
    from recruiter.sourcing.provider import resolve

    fake_settings = type("S", (), {
        "search_provider": "searxng",
        "search_engine_id": None,
    })()
    with pytest.raises(SearchError) as ei:
        resolve(fake_settings)
    assert ei.value.transient is False


def test_factory_raises_when_url_not_http() -> None:
    import recruiter.sourcing  # noqa: F401
    from recruiter.sourcing.provider import resolve

    fake_settings = type("S", (), {
        "search_provider": "searxng",
        "search_engine_id": "localhost:8080",  # missing scheme
    })()
    with pytest.raises(SearchError) as ei:
        resolve(fake_settings)
    assert ei.value.transient is False


def test_factory_strips_trailing_slash() -> None:
    import recruiter.sourcing  # noqa: F401
    from recruiter.sourcing.provider import resolve

    fake_settings = type("S", (), {
        "search_provider": "searxng",
        "search_engine_id": "http://localhost:8080/",
    })()
    p = resolve(fake_settings)
    assert isinstance(p, SearXNGProvider)
    assert p._base_url == "http://localhost:8080"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_searxng.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'recruiter.sourcing.searxng'`.

---

### Task 5: SearXNG provider — implementation

**Files:**
- Create: `src/recruiter/sourcing/searxng.py`
- Modify: `src/recruiter/sourcing/__init__.py`

- [ ] **Step 1: Implement `SearXNGProvider`**

Create `src/recruiter/sourcing/searxng.py`:

```python
import httpx

from recruiter.sourcing.provider import (
    SearchError,
    SearchResult,
    parse_linkedin_name,
    register,
)


class SearXNGProvider:
    """Self-hosted SearXNG provider. Expects the instance to have
    `formats: [json]` in its settings.yml. No auth — assumes trusted
    local-network deployment."""

    def __init__(
        self,
        *,
        base_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(transport=transport, timeout=15.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        url = f"{self._base_url}/search"
        params: dict[str, str | int] = {
            "q": query,
            "format": "json",
            "safesearch": 0,
        }
        try:
            r = await self._client.get(url, params=params)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise SearchError(
                f"can't reach SearXNG at {self._base_url}: {e}",
                transient=True,
            ) from e
        except httpx.HTTPError as e:
            raise SearchError(f"network failure: {e}", transient=True) from e
        if r.status_code != 200:
            raise SearchError(
                f"searxng {r.status_code}: {r.text[:200]}",
                transient=False,
            )
        try:
            payload = r.json()
        except ValueError as e:
            raise SearchError(
                "searxng returned non-JSON; enable formats: [json] in settings.yml",
                transient=False,
            ) from e
        items = payload.get("results") or []
        out: list[SearchResult] = []
        for it in items[:limit]:
            url_value = it.get("url", "")
            if not url_value:
                continue
            title = it.get("title") or ""
            if "linkedin.com" in url_value:
                name = parse_linkedin_name(title) or title or url_value
            else:
                name = title or url_value
            out.append(SearchResult(
                name=name,
                url=url_value,
                snippet=it.get("content", "") or "",
                source="web",
            ))
        return out


@register("searxng")
def _factory(settings) -> SearXNGProvider:
    base = getattr(settings, "search_engine_id", None)
    if not base or not base.startswith(("http://", "https://")):
        raise SearchError(
            "searxng requires search_engine_id to be set to the instance URL "
            "(e.g. http://localhost:8080)",
            transient=False,
        )
    return SearXNGProvider(base_url=base)
```

- [ ] **Step 2: Add the import to the registry chain**

Update `src/recruiter/sourcing/__init__.py` so it now reads:

```python
# noqa imports run the @register decorators in each provider module.
from recruiter.sourcing import google_cse as _google_cse  # noqa: F401
from recruiter.sourcing import brave as _brave  # noqa: F401
from recruiter.sourcing import searxng as _searxng  # noqa: F401
```

- [ ] **Step 3: Run the SearXNG tests**

Run: `uv run pytest tests/unit/test_searxng.py -v`
Expected: all 9 tests PASS.

- [ ] **Step 4: Run full sourcing test suite**

Run: `uv run pytest tests/unit/test_sourcing_provider.py tests/unit/test_sourcing_search.py tests/unit/test_google_cse.py tests/unit/test_brave.py tests/unit/test_searxng.py tests/unit/test_provider_helpers.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/sourcing/searxng.py src/recruiter/sourcing/__init__.py tests/unit/test_searxng.py
git commit -m "feat(sourcing): add self-hosted SearXNG provider"
```

---

### Task 6: Frontend — failing tests for sourcing tab

**Files:**
- Create: `recruiter-frontend/src/components/settings/sourcing-tab.test.tsx`

- [ ] **Step 1: Write the test file**

Create `recruiter-frontend/src/components/settings/sourcing-tab.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { SourcingTab } from "./sourcing-tab";

const server = setupServer();

type Settings = {
  search_provider: string | null;
  search_engine_id: string | null;
  has_search_api_key: boolean;
  has_github_token: boolean;
};

function defaultSettings(overrides: Partial<Settings> = {}): Settings {
  return {
    search_provider: "google_cse",
    search_engine_id: "abcd:1234",
    has_search_api_key: true,
    has_github_token: false,
    ...overrides,
  };
}

function mockSettingsRoutes(initial: Settings, capture: { lastBody?: any }) {
  let current = initial;
  server.use(
    http.get("http://localhost:8000/api/settings", () =>
      HttpResponse.json(current),
    ),
    http.put("http://localhost:8000/api/settings", async ({ request }) => {
      capture.lastBody = await request.json();
      return HttpResponse.json(current);
    }),
  );
}

function renderTab() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <SourcingTab />
      <Toaster />
    </QueryClientProvider>,
  );
}

describe("SourcingTab — multi-provider", () => {
  beforeEach(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => {
    server.resetHandlers();
    server.close();
  });

  it("shows API key + CSE ID for google_cse (default)", async () => {
    const cap: any = {};
    mockSettingsRoutes(defaultSettings(), cap);
    renderTab();
    await waitFor(() => expect(screen.getByLabelText(/CSE ID/i)).toBeInTheDocument());
    expect(screen.getByLabelText(/API key/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Instance URL/i)).not.toBeInTheDocument();
  });

  it("switches to Brave: hides CSE ID, keeps API key", async () => {
    const cap: any = {};
    mockSettingsRoutes(defaultSettings(), cap);
    renderTab();
    await waitFor(() => expect(screen.getByLabelText(/CSE ID/i)).toBeInTheDocument());

    await userEvent.click(screen.getByRole("combobox", { name: /provider/i }));
    await userEvent.click(screen.getByRole("option", { name: /brave search/i }));

    expect(screen.getByLabelText(/API key/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/CSE ID/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Instance URL/i)).not.toBeInTheDocument();
  });

  it("switches to SearXNG: shows Instance URL, hides API key + CSE ID", async () => {
    const cap: any = {};
    mockSettingsRoutes(defaultSettings(), cap);
    renderTab();
    await waitFor(() => expect(screen.getByLabelText(/CSE ID/i)).toBeInTheDocument());

    await userEvent.click(screen.getByRole("combobox", { name: /provider/i }));
    await userEvent.click(screen.getByRole("option", { name: /searxng/i }));

    expect(screen.getByLabelText(/Instance URL/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/API key/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/CSE ID/i)).not.toBeInTheDocument();
  });

  it("save while Brave is selected sends only search_provider + search_api_key", async () => {
    const cap: any = {};
    mockSettingsRoutes(defaultSettings(), cap);
    renderTab();
    await waitFor(() => expect(screen.getByLabelText(/CSE ID/i)).toBeInTheDocument());

    await userEvent.click(screen.getByRole("combobox", { name: /provider/i }));
    await userEvent.click(screen.getByRole("option", { name: /brave search/i }));
    await userEvent.type(screen.getByLabelText(/API key/i), "brv_xyz");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(cap.lastBody).toBeDefined());
    expect(cap.lastBody.search_provider).toBe("brave");
    expect(cap.lastBody.search_api_key).toBe("brv_xyz");
    expect(cap.lastBody).not.toHaveProperty("search_engine_id");
  });

  it("save while SearXNG is selected sends only search_provider + search_engine_id", async () => {
    const cap: any = {};
    mockSettingsRoutes(defaultSettings(), cap);
    renderTab();
    await waitFor(() => expect(screen.getByLabelText(/CSE ID/i)).toBeInTheDocument());

    await userEvent.click(screen.getByRole("combobox", { name: /provider/i }));
    await userEvent.click(screen.getByRole("option", { name: /searxng/i }));
    await userEvent.clear(screen.getByLabelText(/Instance URL/i));
    await userEvent.type(screen.getByLabelText(/Instance URL/i), "http://localhost:8080");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(cap.lastBody).toBeDefined());
    expect(cap.lastBody.search_provider).toBe("searxng");
    expect(cap.lastBody.search_engine_id).toBe("http://localhost:8080");
    expect(cap.lastBody).not.toHaveProperty("search_api_key");
  });

  it("typing in API key under Brave then switching to SearXNG drops the key from the save", async () => {
    const cap: any = {};
    mockSettingsRoutes(defaultSettings(), cap);
    renderTab();
    await waitFor(() => expect(screen.getByLabelText(/CSE ID/i)).toBeInTheDocument());

    // Switch to Brave, type a key.
    await userEvent.click(screen.getByRole("combobox", { name: /provider/i }));
    await userEvent.click(screen.getByRole("option", { name: /brave search/i }));
    await userEvent.type(screen.getByLabelText(/API key/i), "brv_should_not_persist");

    // Switch to SearXNG and save.
    await userEvent.click(screen.getByRole("combobox", { name: /provider/i }));
    await userEvent.click(screen.getByRole("option", { name: /searxng/i }));
    await userEvent.type(screen.getByLabelText(/Instance URL/i), "http://localhost:8080");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(cap.lastBody).toBeDefined());
    expect(cap.lastBody).not.toHaveProperty("search_api_key");
  });
});
```

- [ ] **Step 2: Run the frontend tests to verify they fail**

Run from `recruiter-frontend/`:

```bash
cd recruiter-frontend && npm test -- src/components/settings/sourcing-tab.test.tsx
```

Expected: FAIL — initial test will fail because the new dropdown options ("brave search", "searxng") don't exist yet.

---

### Task 7: Frontend — implement multi-provider sourcing tab

**Files:**
- Modify: `recruiter-frontend/src/components/settings/sourcing-tab.tsx`

- [ ] **Step 1: Replace the file with the multi-provider version**

Overwrite `recruiter-frontend/src/components/settings/sourcing-tab.tsx`:

```tsx
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError } from "@/lib/api";
import { useSettings, useUpdateSettings } from "@/hooks/use-settings";

type Provider = "google_cse" | "brave" | "searxng";

const PROVIDER_LABELS: Record<Provider, string> = {
  google_cse: "Google Custom Search",
  brave: "Brave Search",
  searxng: "SearXNG (self-hosted)",
};

export function SourcingTab() {
  const settings = useSettings();
  const update = useUpdateSettings();
  const [provider, setProvider] = useState<Provider | undefined>();
  const [apiKey, setApiKey] = useState("");
  const [cseOrUrl, setCseOrUrl] = useState<string | undefined>();
  const [ghToken, setGhToken] = useState("");

  // Reset typed inputs whenever the active provider changes so a stale
  // value typed under a previous provider can't leak into the next save.
  useEffect(() => {
    setApiKey("");
    setCseOrUrl(undefined);
  }, [provider]);

  if (settings.isLoading) return <p>Loading…</p>;
  if (!settings.data) return <p>No settings.</p>;

  const cur = settings.data;
  const effProvider = (provider ?? cur.search_provider ?? "google_cse") as Provider;
  // Persisted search_engine_id is meaningful only for the provider it was
  // saved under. When viewing a different provider, start the field empty.
  const persistedRelevant = effProvider === cur.search_provider;
  const effCseOrUrl = cseOrUrl ?? (persistedRelevant ? (cur.search_engine_id ?? "") : "");

  const showApiKey = effProvider === "google_cse" || effProvider === "brave";
  const showCseId = effProvider === "google_cse";
  const showInstanceUrl = effProvider === "searxng";

  function save() {
    const body: Record<string, unknown> = {};
    if (provider !== undefined && provider !== cur.search_provider) {
      body.search_provider = provider;
    } else if (cur.search_provider === null) {
      body.search_provider = effProvider;
    }
    if (showApiKey && apiKey) body.search_api_key = apiKey;
    if ((showCseId || showInstanceUrl) && cseOrUrl !== undefined && cseOrUrl !== (cur.search_engine_id ?? "")) {
      body.search_engine_id = cseOrUrl;
    }
    if (ghToken) body.github_token = ghToken;
    update.mutate(body, {
      onSuccess: () => {
        setApiKey("");
        setGhToken("");
        toast.success("Sourcing settings saved");
      },
      onError: (err) => {
        toast.error(err instanceof ApiError ? err.detail : "Save failed");
      },
    });
  }

  return (
    <div className="space-y-4 max-w-md">
      <div className="space-y-2">
        <Label htmlFor="sourcing-provider">Provider (LinkedIn + Web search)</Label>
        <Select value={effProvider} onValueChange={(v) => setProvider(v as Provider)}>
          <SelectTrigger id="sourcing-provider" aria-label="Provider">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="google_cse">{PROVIDER_LABELS.google_cse}</SelectItem>
            <SelectItem value="brave">{PROVIDER_LABELS.brave}</SelectItem>
            <SelectItem value="searxng">{PROVIDER_LABELS.searxng}</SelectItem>
          </SelectContent>
        </Select>
        {effProvider === "google_cse" && (
          <p className="text-xs text-muted-foreground">
            Configure a Custom Search Engine at{" "}
            <a className="underline" href="https://cse.google.com" target="_blank" rel="noreferrer">
              cse.google.com
            </a>{" "}
            and enable the Custom Search API in Google Cloud Console.
          </p>
        )}
        {effProvider === "brave" && (
          <p className="text-xs text-muted-foreground">
            Free key (no card, 2000 queries/month) at{" "}
            <a className="underline" href="https://brave.com/search/api/" target="_blank" rel="noreferrer">
              brave.com/search/api
            </a>.
          </p>
        )}
        {effProvider === "searxng" && (
          <p className="text-xs text-muted-foreground">
            Run SearXNG via Docker. In <code>settings.yml</code> ensure{" "}
            <code>search.formats</code> includes <code>json</code>.
          </p>
        )}
      </div>

      {showApiKey && (
        <div className="space-y-2">
          <Label htmlFor="sourcing-api-key">API key</Label>
          <Input
            id="sourcing-api-key"
            type="password"
            placeholder={cur.has_search_api_key ? "•••••• (set)" : effProvider === "brave" ? "brv_…" : "AIza…"}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>
      )}

      {showCseId && (
        <div className="space-y-2">
          <Label htmlFor="sourcing-cse-id">CSE ID (cx)</Label>
          <Input
            id="sourcing-cse-id"
            placeholder="abcd1234:efgh5678"
            value={effCseOrUrl}
            onChange={(e) => setCseOrUrl(e.target.value)}
          />
        </div>
      )}

      {showInstanceUrl && (
        <div className="space-y-2">
          <Label htmlFor="sourcing-instance-url">Instance URL</Label>
          <Input
            id="sourcing-instance-url"
            placeholder="http://localhost:8080"
            value={effCseOrUrl}
            onChange={(e) => setCseOrUrl(e.target.value)}
          />
        </div>
      )}

      <div className="space-y-2">
        <Label htmlFor="sourcing-gh-token">GitHub personal access token (optional)</Label>
        <Input
          id="sourcing-gh-token"
          type="password"
          placeholder={
            cur.has_github_token ? "•••••• (set)" : "ghp_… (raises rate limit)"
          }
          value={ghToken}
          onChange={(e) => setGhToken(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          GitHub search works without a token but is limited to 60 requests/hour.
        </p>
      </div>

      <Button onClick={save} disabled={update.isPending}>
        {update.isPending ? "Saving…" : "Save"}
      </Button>
    </div>
  );
}
```

- [ ] **Step 2: Run the frontend tests**

Run from `recruiter-frontend/`:

```bash
cd recruiter-frontend && npm test -- src/components/settings/sourcing-tab.test.tsx
```

Expected: all 6 tests PASS.

- [ ] **Step 3: Run the typecheck**

Run from `recruiter-frontend/`:

```bash
cd recruiter-frontend && npm run lint
```

Expected: no TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add recruiter-frontend/src/components/settings/sourcing-tab.tsx recruiter-frontend/src/components/settings/sourcing-tab.test.tsx
git commit -m "feat(frontend): provider-aware fields in Sourcing tab (Brave + SearXNG)"
```

---

### Task 8: Documentation

**Files:**
- Modify: `docs/setup.md`

- [ ] **Step 1: Append a "Sourcing providers" section**

Append to `docs/setup.md`:

```markdown

## Sourcing providers

Web/LinkedIn search supports three providers; pick one in **Settings → Sourcing**.

### Google Custom Search

- Free 100 queries/day. Requires a Google Cloud project with a billing account attached (the trial 300$ counts).
- Setup:
  1. https://cse.google.com → New search engine → enable "Search the entire web". Copy the **Search engine ID (cx)**.
  2. https://console.cloud.google.com/apis/library/customsearch.googleapis.com → Enable.
  3. https://console.cloud.google.com/apis/credentials → Create credentials → API key. Copy the `AIza…`.
  4. Settings → Sourcing → paste API key + CX → Save.

### Brave Search

- Free 2000 queries/month, no card required.
- Setup:
  1. https://brave.com/search/api/ → sign up → copy the API key (`brv_…`).
  2. Settings → Sourcing → Provider: **Brave Search** → paste API key → Save.

### SearXNG (self-hosted)

- Unlimited; runs locally on your machine.
- Setup:
  1. `docker run --rm -p 8080:8080 -e BASE_URL=http://localhost:8080 searxng/searxng`
  2. In the running container, edit `/etc/searxng/settings.yml` to ensure `search.formats` contains `json` (the default config in the image already has it).
  3. Settings → Sourcing → Provider: **SearXNG (self-hosted)** → Instance URL: `http://localhost:8080` → Save.

### GitHub (separate, for the GitHub tab)

- Works without configuration (60 requests/hour anonymously).
- Optional: Settings → Sourcing → paste a GitHub personal access token (`ghp_…`) to raise the limit to 5000/hour.
```

- [ ] **Step 2: Commit**

```bash
git add docs/setup.md
git commit -m "docs(setup): document Brave + SearXNG sourcing providers"
```

---

### Task 9: Final verification

**Files:** none modified

- [ ] **Step 1: Run the entire backend test suite**

Run: `uv run pytest -x`
Expected: all PASS.

- [ ] **Step 2: Run the entire frontend test suite**

Run from `recruiter-frontend/`:

```bash
cd recruiter-frontend && npm test
```

Expected: all PASS.

- [ ] **Step 3: Lint backend**

Run: `uv run ruff check src tests`
Expected: no issues.

- [ ] **Step 4: Lint frontend**

Run from `recruiter-frontend/`:

```bash
cd recruiter-frontend && npm run lint
```

Expected: no issues.

- [ ] **Step 5: Smoke test in the browser**

Backend + frontend already running (uvicorn + vite). In the browser:
1. Settings → Sourcing → switch to **Brave Search**. Confirm CSE ID field disappears, API key remains.
2. Switch to **SearXNG**. Confirm only Instance URL appears.
3. Switch back to **Google Custom Search**. Confirm both API key and CSE ID appear.

No code changes — visual sanity check only.
