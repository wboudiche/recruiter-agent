# Candidate Search (Plan F) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three chat-agent tools (`search_linkedin`, `search_github`, `search_web`) that surface web-sourced candidates as cards in the chat panel; clicking "Add" funnels them through the existing candidate-creation endpoint.

**Architecture:** New `src/recruiter/sourcing/` module with a `SearchProvider` Protocol + registry. Google CSE is the v1 default provider; GitHub uses its own REST API directly (no abstraction). Tool handlers live in `agent/tools.py` next to the existing ones; they return a short text summary to the LLM AND append a frontend-only `tool.search_results` event to a new `ToolContext.frontend_events` list that the agent loop emits onto the NDJSON stream.

**Tech Stack:** Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic + httpx (backend); React 18 + Vite + TanStack Query v5 + msw + vitest (frontend).

---

## Task 1: Settings — schema, model columns, migration, /api/settings

**Files:**
- Modify: `src/recruiter/models/settings.py`
- Modify: `src/recruiter/schemas/settings.py`
- Modify: `src/recruiter/api/settings.py`
- Create: `alembic/versions/<timestamp>_search_settings.py`
- Modify: `tests/api/test_settings_api.py`

- [ ] **Step 1: Write the failing test** (`tests/api/test_settings_api.py` — append)

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_put_settings_persists_search_provider_and_keys(
    api_client: AsyncClient,
) -> None:
    r = await api_client.put("/api/settings", json={
        "search_provider": "google_cse",
        "search_api_key": "google-api-key",
        "search_engine_id": "abcd1234:efgh5678",
        "github_token": "ghp_xxx",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["search_provider"] == "google_cse"
    assert body["search_engine_id"] == "abcd1234:efgh5678"
    assert body["has_search_api_key"] is True
    assert body["has_github_token"] is True
    # Round-trip: GET reflects what we set.
    r = await api_client.get("/api/settings")
    body = r.json()
    assert body["search_provider"] == "google_cse"
    assert body["has_search_api_key"] is True


@pytest.mark.asyncio
async def test_get_settings_defaults_search_unset(api_client: AsyncClient) -> None:
    r = await api_client.get("/api/settings")
    body = r.json()
    assert body["search_provider"] is None
    assert body["search_engine_id"] is None
    assert body["has_search_api_key"] is False
    assert body["has_github_token"] is False
```

- [ ] **Step 2: Run test, verify fail**

Run: `.venv/bin/pytest tests/api/test_settings_api.py -v -k search`
Expected: FAIL — `KeyError`/422 because the new fields don't exist yet.

- [ ] **Step 3: Add columns to the model**

Edit `src/recruiter/models/settings.py`. Inside `SettingsRow`, after `monthly_llm_spend_cap_usd`, add:

```python
    search_provider: Mapped[str | None] = mapped_column(String(32))
    search_api_key_enc: Mapped[str | None] = mapped_column(String)
    search_engine_id: Mapped[str | None] = mapped_column(String(255))
    github_token_enc: Mapped[str | None] = mapped_column(String)
```

- [ ] **Step 4: Create the Alembic migration**

Run: `.venv/bin/alembic revision -m "add search settings columns"`

Edit the generated file to:

```python
"""add search settings columns"""
from alembic import op
import sqlalchemy as sa


revision = "<keep auto-generated>"
down_revision = "<keep auto-generated>"


def upgrade() -> None:
    op.add_column("settings", sa.Column("search_provider", sa.String(32), nullable=True))
    op.add_column("settings", sa.Column("search_api_key_enc", sa.String(), nullable=True))
    op.add_column("settings", sa.Column("search_engine_id", sa.String(255), nullable=True))
    op.add_column("settings", sa.Column("github_token_enc", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("settings", "github_token_enc")
    op.drop_column("settings", "search_engine_id")
    op.drop_column("settings", "search_api_key_enc")
    op.drop_column("settings", "search_provider")
```

- [ ] **Step 5: Apply the migration**

Run: `.venv/bin/alembic upgrade head`
Expected: clean upgrade.

- [ ] **Step 6: Update Pydantic schemas**

Edit `src/recruiter/schemas/settings.py`. Inside `SettingsRead`, add after `monthly_llm_spend_cap_usd`:

```python
    search_provider: str | None = None
    search_engine_id: str | None = None
    has_search_api_key: bool = False
    has_github_token: bool = False
```

Inside `SettingsUpdate`, add:

```python
    search_provider: str | None = None
    search_api_key: str | None = None
    search_engine_id: str | None = None
    github_token: str | None = None
```

- [ ] **Step 7: Wire the API**

Edit `src/recruiter/api/settings.py`. Update `_to_read`:

```python
def _to_read(row: SettingsRow) -> SettingsRead:
    return SettingsRead(
        default_llm_provider=row.default_llm_provider,
        has_anthropic_api_key=bool(row.anthropic_api_key_enc),
        local_llm_url=row.local_llm_url,
        has_local_llm_api_key=bool(row.local_llm_api_key_enc),
        model_overrides=row.model_overrides or {},
        has_google_oauth_tokens=bool(row.google_oauth_tokens_enc),
        has_smtp_config=bool(row.smtp_config_enc),
        recruiter_name=row.recruiter_name,
        recruiter_email=row.recruiter_email,
        monthly_llm_spend_cap_usd=row.monthly_llm_spend_cap_usd,
        search_provider=row.search_provider,
        search_engine_id=row.search_engine_id,
        has_search_api_key=bool(row.search_api_key_enc),
        has_github_token=bool(row.github_token_enc),
    )
```

In `update_settings`, after the existing `if payload.monthly_llm_spend_cap_usd is not None:` block, add:

```python
    if payload.search_provider is not None:
        row.search_provider = payload.search_provider
    if payload.search_api_key is not None:
        row.search_api_key_enc = cipher.encrypt(payload.search_api_key)
    if payload.search_engine_id is not None:
        row.search_engine_id = payload.search_engine_id
    if payload.github_token is not None:
        row.github_token_enc = cipher.encrypt(payload.github_token)
```

- [ ] **Step 8: Run the test, verify pass**

Run: `.venv/bin/pytest tests/api/test_settings_api.py -v -k search`
Expected: 2 PASS.

Run: `.venv/bin/pytest -q`
Expected: full suite still green (212 + 2 new = 214).

- [ ] **Step 9: Commit**

```bash
git add src/recruiter/models/settings.py \
        src/recruiter/schemas/settings.py \
        src/recruiter/api/settings.py \
        alembic/versions/*search* \
        tests/api/test_settings_api.py
git commit -m "feat(settings): add search provider + api key + cse id + github token columns"
```

---

## Task 2: Sourcing — provider Protocol, SearchResult, registry

**Files:**
- Create: `src/recruiter/sourcing/__init__.py`
- Create: `src/recruiter/sourcing/provider.py`
- Create: `tests/unit/test_sourcing_provider.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_sourcing_provider.py`:

```python
import pytest

from recruiter.sourcing.provider import (
    SearchError,
    SearchProvider,
    SearchResult,
    register,
    resolve,
)


class _Stub(SearchProvider):
    async def search(self, query: str, limit: int) -> list[SearchResult]:
        return [SearchResult(name="x", url="https://x", snippet="y", source="web")]


def test_search_result_holds_required_fields() -> None:
    r = SearchResult(name="Alice", url="https://x", snippet="bio", source="linkedin")
    assert r.name == "Alice"
    assert r.source == "linkedin"


def test_search_error_carries_transient_flag() -> None:
    e = SearchError(message="rate limit", transient=True)
    assert e.transient is True
    assert "rate limit" in str(e)


def test_registry_resolves_registered_provider() -> None:
    @register("stub")
    def _factory(_settings):
        return _Stub()

    fake_settings = type("S", (), {"search_provider": "stub", "search_api_key_enc": b"x", "search_engine_id": "y"})()
    p = resolve(fake_settings)
    assert isinstance(p, _Stub)


def test_registry_returns_none_when_unconfigured() -> None:
    fake_settings = type("S", (), {"search_provider": None})()
    assert resolve(fake_settings) is None


def test_registry_returns_none_for_unknown_provider() -> None:
    fake_settings = type("S", (), {"search_provider": "nonexistent"})()
    assert resolve(fake_settings) is None
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/pytest tests/unit/test_sourcing_provider.py -v`
Expected: collection error — module doesn't exist.

- [ ] **Step 3: Implement**

Create `src/recruiter/sourcing/__init__.py` (empty file).

Create `src/recruiter/sourcing/provider.py`:

```python
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol


@dataclass
class SearchResult:
    name: str
    url: str
    snippet: str
    source: Literal["linkedin", "github", "web"]


class SearchError(Exception):
    """Raised by providers when a search call fails. `transient` distinguishes
    rate-limit / network failures (retryable later by the user) from
    config / auth failures (require Settings change)."""

    def __init__(self, message: str, *, transient: bool) -> None:
        super().__init__(message)
        self.transient = transient


class SearchProvider(Protocol):
    async def search(self, query: str, limit: int) -> list[SearchResult]: ...


# Module-level registry. Factories are called with a SettingsRow; they pull
# the credentials they need and return a configured SearchProvider instance.
_FACTORIES: dict[str, Callable[[Any], SearchProvider]] = {}


def register(name: str) -> Callable[[Callable[[Any], SearchProvider]], Callable[[Any], SearchProvider]]:
    def deco(factory: Callable[[Any], SearchProvider]) -> Callable[[Any], SearchProvider]:
        _FACTORIES[name] = factory
        return factory
    return deco


def resolve(settings: Any) -> SearchProvider | None:
    """Return a configured provider for the SettingsRow, or None if unset
    or registered factory missing."""
    name = getattr(settings, "search_provider", None)
    if not name:
        return None
    factory = _FACTORIES.get(name)
    if factory is None:
        return None
    return factory(settings)
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/pytest tests/unit/test_sourcing_provider.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/sourcing/__init__.py \
        src/recruiter/sourcing/provider.py \
        tests/unit/test_sourcing_provider.py
git commit -m "feat(sourcing): add SearchProvider Protocol + SearchResult + registry"
```

---

## Task 3: Google CSE provider

**Files:**
- Create: `src/recruiter/sourcing/google_cse.py`
- Create: `tests/unit/test_google_cse.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_google_cse.py`:

```python
import httpx
import pytest

from recruiter.sourcing.google_cse import GoogleCSEProvider
from recruiter.sourcing.provider import SearchError


def _make_provider(transport: httpx.MockTransport) -> GoogleCSEProvider:
    return GoogleCSEProvider(api_key="k", cse_id="cx", transport=transport)


@pytest.mark.asyncio
async def test_search_returns_results_for_200() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/customsearch/v1")
        assert "q=site%3Alinkedin.com" in str(req.url) or "site:linkedin.com" in str(req.url)
        return httpx.Response(200, json={
            "items": [
                {"title": "Alice Doe - Senior Rust Engineer | LinkedIn",
                 "link": "https://www.linkedin.com/in/alice/",
                 "snippet": "5 years Rust, async / Postgres."},
                {"title": "Bob | LinkedIn",
                 "link": "https://www.linkedin.com/in/bob/",
                 "snippet": "Backend engineer."},
            ],
        })
    p = _make_provider(httpx.MockTransport(handler))
    results = await p.search("site:linkedin.com/in/ rust engineer", 5)
    assert len(results) == 2
    assert results[0].name == "Alice Doe"  # parsed before the first " - "
    assert results[0].url == "https://www.linkedin.com/in/alice/"
    assert "5 years Rust" in results[0].snippet
    assert results[0].source == "web"  # provider doesn't set source; tools do


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_items() -> None:
    handler = lambda req: httpx.Response(200, json={"queries": {}})
    p = _make_provider(httpx.MockTransport(handler))
    assert await p.search("zzznoresultsxxx", 5) == []


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
async def test_search_falls_back_to_link_when_title_missing() -> None:
    handler = lambda req: httpx.Response(200, json={
        "items": [{"link": "https://example.com/", "snippet": "no title"}],
    })
    p = _make_provider(httpx.MockTransport(handler))
    results = await p.search("x", 5)
    assert results[0].name == "https://example.com/"
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/pytest tests/unit/test_google_cse.py -v`
Expected: collection error — module doesn't exist.

- [ ] **Step 3: Implement**

Create `src/recruiter/sourcing/google_cse.py`:

```python
import httpx

from recruiter.sourcing.provider import SearchError, SearchResult


GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"


def _parse_name(title: str | None) -> str | None:
    """LinkedIn titles look like 'Alice Doe - Senior Rust | LinkedIn'.
    Strip the '| LinkedIn' suffix and take the first ' - ' segment.
    Returns None if the title is empty."""
    if not title:
        return None
    cleaned = title.split(" | ")[0].strip()
    return cleaned.split(" - ")[0].strip() or None


class GoogleCSEProvider:
    """Google Custom Search Engine provider. Configure a CSE in cse.google.com,
    set its CX, and pass it here along with a Google Cloud API key with
    Custom Search API enabled."""

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
        params = {
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
            name = _parse_name(it.get("title")) or link
            out.append(SearchResult(
                name=name, url=link, snippet=it.get("snippet", "") or "", source="web",
            ))
        return out
```

Note: `source="web"` is the **provider-level** value. The chat tool wrapper (Task 6) overrides it to `linkedin` or `web` based on which tool was called.

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/pytest tests/unit/test_google_cse.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Register the factory**

Append to `src/recruiter/sourcing/google_cse.py`:

```python
from recruiter.sourcing.provider import register
from recruiter.crypto import SecretCipher
from recruiter.config import get_config


def _decrypt_settings_key(settings) -> str:
    """Decrypt search_api_key_enc using the standard SettingsCipher.
    Mirrors api/settings.py:_cipher() but importable for the registry factory."""
    raw = get_config().settings_key
    if len(raw) == 64:
        key = bytes.fromhex(raw)
    else:
        key = raw.encode("utf-8")
    cipher = SecretCipher(key)
    return cipher.decrypt(settings.search_api_key_enc)


@register("google_cse")
def _factory(settings) -> GoogleCSEProvider:
    if not settings.search_api_key_enc or not settings.search_engine_id:
        raise SearchError(
            "google_cse requires both search_api_key and search_engine_id",
            transient=False,
        )
    return GoogleCSEProvider(
        api_key=_decrypt_settings_key(settings),
        cse_id=settings.search_engine_id,
    )
```

- [ ] **Step 6: Run again to confirm registration didn't break**

Run: `.venv/bin/pytest tests/unit/test_google_cse.py tests/unit/test_sourcing_provider.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/recruiter/sourcing/google_cse.py tests/unit/test_google_cse.py
git commit -m "feat(sourcing): Google CSE provider + registry factory"
```

---

## Task 4: GitHub search client

**Files:**
- Create: `src/recruiter/sourcing/github.py`
- Create: `tests/unit/test_github_search.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_github_search.py`:

```python
import httpx
import pytest

from recruiter.sourcing.github import GitHubSearchClient
from recruiter.sourcing.provider import SearchError


def _client(transport: httpx.MockTransport, *, token: str | None = None) -> GitHubSearchClient:
    return GitHubSearchClient(token=token, transport=transport)


@pytest.mark.asyncio
async def test_search_users_returns_results() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/search/users"
        # Token is sent as Authorization header when provided.
        return httpx.Response(200, json={
            "total_count": 2,
            "items": [
                {"login": "alice", "html_url": "https://github.com/alice", "type": "User"},
                {"login": "bob", "html_url": "https://github.com/bob", "type": "User"},
            ],
        })

    c = _client(httpx.MockTransport(handler))
    results = await c.search_users("rust async", 5)
    assert len(results) == 2
    assert results[0].name == "alice"
    assert results[0].url == "https://github.com/alice"
    assert results[0].source == "github"


@pytest.mark.asyncio
async def test_search_users_sends_token_when_set() -> None:
    auth_seen: dict = {}
    def handler(req: httpx.Request) -> httpx.Response:
        auth_seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"items": []})

    c = _client(httpx.MockTransport(handler), token="ghp_abc")
    await c.search_users("x", 5)
    assert auth_seen["auth"] == "Bearer ghp_abc"


@pytest.mark.asyncio
async def test_search_users_omits_auth_header_when_no_token() -> None:
    auth_seen: dict = {}
    def handler(req: httpx.Request) -> httpx.Response:
        auth_seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"items": []})

    c = _client(httpx.MockTransport(handler), token=None)
    await c.search_users("x", 5)
    assert auth_seen["auth"] is None


@pytest.mark.asyncio
async def test_search_users_raises_transient_on_403_rate_limit() -> None:
    handler = lambda req: httpx.Response(403, json={"message": "rate limit exceeded"})
    c = _client(httpx.MockTransport(handler))
    with pytest.raises(SearchError) as ei:
        await c.search_users("x", 5)
    assert ei.value.transient is True


@pytest.mark.asyncio
async def test_search_users_raises_config_on_401() -> None:
    handler = lambda req: httpx.Response(401, text="bad token")
    c = _client(httpx.MockTransport(handler), token="ghp_bad")
    with pytest.raises(SearchError) as ei:
        await c.search_users("x", 5)
    assert ei.value.transient is False
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/pytest tests/unit/test_github_search.py -v`
Expected: collection error.

- [ ] **Step 3: Implement**

Create `src/recruiter/sourcing/github.py`:

```python
import httpx

from recruiter.sourcing.provider import SearchError, SearchResult


GITHUB_SEARCH_URL = "https://api.github.com/search/users"


class GitHubSearchClient:
    """Direct REST client for GitHub's /search/users endpoint.

    Standalone — does not implement SearchProvider Protocol because GitHub
    doesn't fit the same query-shape model (no `site:` operator equivalent).
    Token is optional; presence raises rate limit from 60/hr to 5000/hr.
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = token
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search_users(self, query: str, limit: int) -> list[SearchResult]:
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        params = {"q": query, "per_page": max(1, min(limit, 30))}
        try:
            r = await self._client.get(GITHUB_SEARCH_URL, headers=headers, params=params)
        except httpx.HTTPError as e:
            raise SearchError(f"network failure: {e}", transient=True) from e
        if r.status_code == 401:
            raise SearchError(f"github auth: {r.text[:200]}", transient=False)
        if r.status_code == 403:
            # GitHub returns 403 for rate-limit; transient.
            raise SearchError(f"github rate-limit/forbidden: {r.text[:200]}", transient=True)
        if r.status_code >= 500:
            raise SearchError(f"github {r.status_code}", transient=True)
        if r.status_code != 200:
            raise SearchError(f"github {r.status_code}: {r.text[:200]}", transient=False)
        items = r.json().get("items", []) or []
        return [
            SearchResult(
                name=it.get("login", ""),
                url=it.get("html_url", ""),
                snippet=f"GitHub user — {it.get('type', 'User')}",
                source="github",
            )
            for it in items
            if it.get("html_url")
        ]
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/pytest tests/unit/test_github_search.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/sourcing/github.py tests/unit/test_github_search.py
git commit -m "feat(sourcing): GitHub /search/users client"
```

---

## Task 5: ToolContext.frontend_events plumbing

**Files:**
- Modify: `src/recruiter/agent/tools.py` (the `ToolContext` dataclass)
- Modify: `src/recruiter/agent/chat.py` (emit events from ctx after handler returns)
- Create: `tests/unit/test_chat_frontend_events.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_chat_frontend_events.py`:

```python
import pytest

from recruiter.agent.tools import ToolContext


def test_tool_context_has_default_empty_frontend_events() -> None:
    ctx = ToolContext(session=None, application_id=1, undo_store=None)  # type: ignore[arg-type]
    assert ctx.frontend_events == []


def test_tool_context_frontend_events_is_independent_per_instance() -> None:
    ctx1 = ToolContext(session=None, application_id=1, undo_store=None)  # type: ignore[arg-type]
    ctx2 = ToolContext(session=None, application_id=2, undo_store=None)  # type: ignore[arg-type]
    ctx1.frontend_events.append({"x": 1})
    assert ctx2.frontend_events == []
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/pytest tests/unit/test_chat_frontend_events.py -v`
Expected: FAIL — `frontend_events` missing on ToolContext.

- [ ] **Step 3: Add the field to ToolContext**

Edit `src/recruiter/agent/tools.py`. The dataclass currently is:

```python
@dataclass
class ToolContext:
    session: AsyncSession
    application_id: int
    undo_store: UndoStore
```

Replace with:

```python
@dataclass
class ToolContext:
    """Per-turn context passed uniformly to every tool handler."""
    session: AsyncSession
    application_id: int
    undo_store: UndoStore
    frontend_events: list[dict] = field(default_factory=list)
```

Add `from dataclasses import dataclass, field` at the top of the file (replace the existing `from dataclasses import dataclass`).

- [ ] **Step 4: Drain events in the agent loop**

Edit `src/recruiter/agent/chat.py`. Find the loop body inside `for tc in turn.tool_calls:`. After the existing `yield tool_call_result_event(...)` line, add:

```python
            # Drain any frontend-only side events the handler accumulated.
            for ev in ctx.frontend_events:
                yield ev
            ctx.frontend_events.clear()
```

- [ ] **Step 5: Run unit test**

Run: `.venv/bin/pytest tests/unit/test_chat_frontend_events.py -v`
Expected: 2 PASS.

- [ ] **Step 6: Run full chat tests to confirm no regression**

Run: `.venv/bin/pytest tests/ -k chat -v`
Expected: no regressions in existing chat tests.

Run: `.venv/bin/pytest -q`
Expected: full suite green (216 passed).

- [ ] **Step 7: Commit**

```bash
git add src/recruiter/agent/tools.py src/recruiter/agent/chat.py tests/unit/test_chat_frontend_events.py
git commit -m "feat(agent): ToolContext.frontend_events for tool-emitted side events"
```

---

## Task 6: Three search tool handlers + tool.search_results event factory

**Files:**
- Modify: `src/recruiter/agent/events.py` (new event factory)
- Modify: `src/recruiter/agent/tools.py` (3 new handlers + ToolDefs)
- Create: `tests/unit/test_sourcing_tools.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_sourcing_tools.py`:

```python
import pytest

from recruiter.agent.tools import ToolContext, get_tool_handler
from recruiter.sourcing.provider import SearchError, SearchResult


class _FakeProvider:
    def __init__(self, results=None, raises=None) -> None:
        self._results = results or []
        self._raises = raises

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        if self._raises:
            raise self._raises
        return self._results


@pytest.fixture
def fake_settings():
    """Mutable namespace mimicking SettingsRow shape."""
    return type("S", (), {
        "search_provider": "google_cse",
        "search_api_key_enc": b"x",
        "search_engine_id": "cx",
        "github_token_enc": None,
    })()


@pytest.mark.asyncio
async def test_search_linkedin_returns_summary_and_emits_event(
    fake_settings, monkeypatch,
) -> None:
    fake = _FakeProvider(results=[
        SearchResult(name="Alice", url="https://www.linkedin.com/in/alice/",
                     snippet="Rust dev", source="web"),
    ])
    # Patch resolve() to return our fake.
    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _s: fake)
    # Patch the settings loader the tool uses.
    import recruiter.agent.tools as tools_mod
    async def _load_settings(_session): return fake_settings
    monkeypatch.setattr(tools_mod, "_load_settings_for_tool", _load_settings)

    ctx = ToolContext(session=None, application_id=1, undo_store=None)  # type: ignore[arg-type]
    handler = get_tool_handler("search_linkedin")
    result = await handler(ctx, {"query": "rust dev", "limit": 5})

    # Text returned to the LLM is a concise summary, not the structured cards.
    assert isinstance(result, dict)
    assert "summary" in result
    assert "Alice" in result["summary"]
    # The structured event was pushed onto ctx.frontend_events.
    assert len(ctx.frontend_events) == 1
    ev = ctx.frontend_events[0]
    assert ev["type"] == "tool.search_results"
    assert ev["tool_name"] == "search_linkedin"
    assert ev["source"] == "linkedin"
    assert ev["results"][0]["name"] == "Alice"
    # source on individual cards is overridden by the tool wrapper.
    assert ev["results"][0]["source"] == "linkedin"


@pytest.mark.asyncio
async def test_search_linkedin_returns_error_text_when_provider_unconfigured(
    monkeypatch,
) -> None:
    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _s: None)
    import recruiter.agent.tools as tools_mod
    async def _load_settings(_session): return type("S", (), {"search_provider": None})()
    monkeypatch.setattr(tools_mod, "_load_settings_for_tool", _load_settings)

    ctx = ToolContext(session=None, application_id=1, undo_store=None)  # type: ignore[arg-type]
    handler = get_tool_handler("search_linkedin")
    result = await handler(ctx, {"query": "x"})
    assert "not configured" in result["summary"].lower()
    assert ctx.frontend_events == []  # no event when nothing was searched


@pytest.mark.asyncio
async def test_search_linkedin_returns_text_when_provider_raises_transient(
    fake_settings, monkeypatch,
) -> None:
    fake = _FakeProvider(raises=SearchError("rate limit", transient=True))
    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _s: fake)
    import recruiter.agent.tools as tools_mod
    async def _load_settings(_session): return fake_settings
    monkeypatch.setattr(tools_mod, "_load_settings_for_tool", _load_settings)

    ctx = ToolContext(session=None, application_id=1, undo_store=None)  # type: ignore[arg-type]
    handler = get_tool_handler("search_linkedin")
    result = await handler(ctx, {"query": "x"})
    assert "temporarily unavailable" in result["summary"].lower()
    assert ctx.frontend_events == []


@pytest.mark.asyncio
async def test_search_github_uses_github_client_not_provider(
    fake_settings, monkeypatch,
) -> None:
    """search_github is wired to GitHubSearchClient directly, not the provider
    registry. With no github_token configured it still works (anonymous)."""
    captured: dict = {}

    class _FakeGH:
        def __init__(self, *, token, transport=None) -> None:
            captured["token"] = token

        async def search_users(self, q, limit):
            return [SearchResult(name="alice", url="https://github.com/alice",
                                 snippet="x", source="github")]

        async def aclose(self): pass

    import recruiter.agent.tools as tools_mod
    async def _load_settings(_session): return fake_settings  # token=None
    monkeypatch.setattr(tools_mod, "_load_settings_for_tool", _load_settings)
    monkeypatch.setattr(tools_mod, "GitHubSearchClient", _FakeGH)

    ctx = ToolContext(session=None, application_id=1, undo_store=None)  # type: ignore[arg-type]
    handler = get_tool_handler("search_github")
    result = await handler(ctx, {"query": "rust"})
    assert "alice" in result["summary"]
    assert captured["token"] is None  # no token configured = anonymous fine
    assert ctx.frontend_events[0]["source"] == "github"
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/pytest tests/unit/test_sourcing_tools.py -v`
Expected: FAIL — handlers `search_linkedin` / `search_github` not registered.

- [ ] **Step 3: Add the event factory**

Edit `src/recruiter/agent/events.py`. After `error_event`, add:

```python
def tool_search_results_event(
    *, tool_name: str, source: Literal["linkedin", "github", "web"], results: list[dict],
) -> dict:
    """Frontend-only event carrying structured search-result cards.
    Not fed back to the LLM (the tool handler returns a text summary
    separately for that)."""
    return {
        "type": "tool.search_results",
        "tool_name": tool_name,
        "source": source,
        "results": results,
    }
```

- [ ] **Step 4: Add the tool handlers**

Edit `src/recruiter/agent/tools.py`. At the top, add imports (consolidate with existing):

```python
from recruiter.crypto import SecretCipher
from recruiter.config import get_config
from recruiter.models import SettingsRow
from recruiter.sourcing import provider as sourcing_provider
from recruiter.sourcing.github import GitHubSearchClient
from recruiter.sourcing.provider import SearchError, SearchResult
from recruiter.agent.events import tool_search_results_event
```

(Skip imports already present.)

Then add module-level helpers + handlers (place before the `TOOLS` list):

```python
async def _load_settings_for_tool(session) -> SettingsRow | None:
    """Load the singleton Settings row. Tools call this rather than
    SettingsRow direct so tests can monkeypatch a single seam."""
    return await session.get(SettingsRow, 1)


def _decrypt_github_token(settings: SettingsRow) -> str | None:
    if not settings.github_token_enc:
        return None
    raw = get_config().settings_key
    key = bytes.fromhex(raw) if len(raw) == 64 else raw.encode("utf-8")
    return SecretCipher(key).decrypt(settings.github_token_enc)


def _format_results_for_llm(results: list[SearchResult]) -> str:
    if not results:
        return "No results found."
    lines = [f"Found {len(results)} result(s):"]
    for i, r in enumerate(results, 1):
        snippet = r.snippet[:120] + "…" if len(r.snippet) > 120 else r.snippet
        lines.append(f"{i}. {r.name} — {r.url} — {snippet}")
    return "\n".join(lines)


async def _run_provider_search(
    ctx: "ToolContext", *, query: str, limit: int, source: str, tool_name: str,
) -> dict:
    settings = await _load_settings_for_tool(ctx.session)
    if settings is None:
        return {"summary": "Search isn't configured. Set a provider in Settings → Sourcing."}
    provider = sourcing_provider.resolve(settings)
    if provider is None:
        return {"summary": "Search isn't configured. Set a provider in Settings → Sourcing."}
    try:
        results = await provider.search(query, limit)
    except SearchError as e:
        if e.transient:
            return {"summary": f"Search temporarily unavailable: {e}."}
        return {"summary": f"Search isn't configured correctly: {e}. Set it in Settings → Sourcing."}
    # Override per-card source from the provider's generic value.
    for r in results:
        r.source = source  # type: ignore[assignment]
    cards = [{"name": r.name, "url": r.url, "snippet": r.snippet, "source": r.source}
             for r in results]
    if cards:
        ctx.frontend_events.append(tool_search_results_event(
            tool_name=tool_name, source=source, results=cards,
        ))
    return {"summary": _format_results_for_llm(results)}


@_register("search_linkedin")
async def _search_linkedin(ctx: "ToolContext", args: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"summary": "query is required"}
    limit = max(1, min(int(args.get("limit") or 5), 10))
    # Constrain to LinkedIn profile URLs.
    return await _run_provider_search(
        ctx, query=f"site:linkedin.com/in/ {query}", limit=limit,
        source="linkedin", tool_name="search_linkedin",
    )


@_register("search_web")
async def _search_web(ctx: "ToolContext", args: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"summary": "query is required"}
    limit = max(1, min(int(args.get("limit") or 5), 10))
    return await _run_provider_search(
        ctx, query=query, limit=limit, source="web", tool_name="search_web",
    )


@_register("search_github")
async def _search_github(ctx: "ToolContext", args: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"summary": "query is required"}
    limit = max(1, min(int(args.get("limit") or 5), 30))
    settings = await _load_settings_for_tool(ctx.session)
    token = _decrypt_github_token(settings) if settings else None
    client = GitHubSearchClient(token=token)
    try:
        results = await client.search_users(query, limit)
    except SearchError as e:
        await client.aclose()
        if e.transient:
            return {"summary": f"GitHub search temporarily unavailable: {e}."}
        return {"summary": f"GitHub search misconfigured: {e}."}
    finally:
        await client.aclose()
    cards = [{"name": r.name, "url": r.url, "snippet": r.snippet, "source": "github"}
             for r in results]
    if cards:
        ctx.frontend_events.append(tool_search_results_event(
            tool_name="search_github", source="github", results=cards,
        ))
    return {"summary": _format_results_for_llm(results)}
```

- [ ] **Step 5: Add ToolDefs**

In `src/recruiter/agent/tools.py`, append three entries to the existing `TOOLS` list (just before the closing `]`):

```python
    ToolDef(
        name="search_linkedin",
        description="Search the open web for LinkedIn profiles matching the query. Returns up to 'limit' result cards (name, URL, snippet). The user can click 'Add' on a card to add the candidate.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text search like 'senior Rust engineer Berlin'."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    ToolDef(
        name="search_github",
        description="Search GitHub for users matching the query. Returns up to 'limit' user cards.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 5},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    ToolDef(
        name="search_web",
        description="Search the open web (any site) for the query. Returns up to 'limit' web result cards. Use for personal sites, conference talks, blog posts.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
```

- [ ] **Step 6: Run, verify pass**

Run: `.venv/bin/pytest tests/unit/test_sourcing_tools.py -v`
Expected: 4 PASS.

Run: `.venv/bin/pytest -q`
Expected: full suite green (220 passed).

- [ ] **Step 7: Commit**

```bash
git add src/recruiter/agent/events.py \
        src/recruiter/agent/tools.py \
        tests/unit/test_sourcing_tools.py
git commit -m "feat(agent): search_linkedin / search_github / search_web chat tools"
```

---

## Task 7: Backend integration test — chat flow emits search results

**Files:**
- Create: `tests/api/test_chat_search_tool.py`

- [ ] **Step 1: Write the test**

Create `tests/api/test_chat_search_tool.py`:

```python
import json

import pytest
from httpx import AsyncClient

from recruiter.agent.types import AssistantTurn, ToolCall
from recruiter.sourcing.provider import SearchResult


@pytest.mark.asyncio
async def test_chat_search_linkedin_emits_tool_search_results_event(
    api_client: AsyncClient, monkeypatch,
) -> None:
    # 1. Stub the LLM to return a tool_use, then a final text on the second call.
    calls = {"n": 0}

    class _StubLLM:
        async def chat_with_tools(self, history, tools, *, system):
            calls["n"] += 1
            if calls["n"] == 1:
                return AssistantTurn(text=None, tool_calls=[
                    ToolCall(id="t1", name="search_linkedin",
                             arguments={"query": "rust dev", "limit": 2}),
                ])
            return AssistantTurn(text="Found candidates.", tool_calls=[])

    # 2. Stub the sourcing provider.
    class _StubProvider:
        async def search(self, q, n):
            return [
                SearchResult(name="Alice", url="https://www.linkedin.com/in/alice/",
                             snippet="Rust dev", source="web"),
            ]

    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _s: _StubProvider())

    from recruiter.api import candidates as candidates_api
    monkeypatch.setattr(candidates_api, "get_llm", lambda: _StubLLM())

    # 3. Create job, candidate, application via the existing helpers
    #    (or use any fixture providing a scored application).
    job = (await api_client.post("/api/jobs", json={
        "title": "Rust eng", "description": "x", "criteria": [],
    })).json()
    job_id = job["id"]
    create = await api_client.post(f"/api/jobs/{job_id}/candidates", json={
        "kind": "paste", "content": "Bob — Rust dev",
    })
    application_id = create.json()["application_id"]
    # Force the application out of extracting so chat is allowed.
    await api_client.patch(f"/api/applications/{application_id}", json={"stage": "scored"})

    # 4. POST chat — read the streamed NDJSON.
    r = await api_client.post(
        f"/api/applications/{application_id}/chat",
        json={"message": "find me rust devs"},
    )
    assert r.status_code == 200
    events = [json.loads(line) for line in r.text.splitlines() if line.strip()]
    types = [e["type"] for e in events]
    assert "tool.search_results" in types
    sr = next(e for e in events if e["type"] == "tool.search_results")
    assert sr["tool_name"] == "search_linkedin"
    assert sr["source"] == "linkedin"
    assert sr["results"][0]["name"] == "Alice"
```

- [ ] **Step 2: Run, expect PASS or FAIL**

Run: `.venv/bin/pytest tests/api/test_chat_search_tool.py -v`

If FAIL because the stub LLM isn't reachable (the existing test setup may construct a real LLM via Settings), study `tests/api/conftest.py` for the existing pattern (the chat tests likely already monkeypatch `get_llm`). Adjust the monkeypatch target to match the real seam.

If PASS: you're done.

- [ ] **Step 3: Run full suite**

Run: `.venv/bin/pytest -q`
Expected: 221 passed.

- [ ] **Step 4: Commit**

```bash
git add tests/api/test_chat_search_tool.py
git commit -m "test(agent): integration — chat search tool emits structured event"
```

---

## Task 8: Frontend — SearchResultCard component

**Files:**
- Create: `recruiter-frontend/src/components/applications/search-result-card.tsx`
- Create: `recruiter-frontend/src/components/applications/search-result-card.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `recruiter-frontend/src/components/applications/search-result-card.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { SearchResultCard } from "./search-result-card";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

const RESULT = {
  name: "Alice Doe",
  url: "https://www.linkedin.com/in/alice/",
  snippet: "5 years Rust",
  source: "linkedin" as const,
};

describe("SearchResultCard", () => {
  it("renders name, source, snippet, and url", () => {
    const Wrapper = wrap();
    render(<Wrapper><SearchResultCard result={RESULT} jobId={1} /></Wrapper>);
    expect(screen.getByText("Alice Doe")).toBeInTheDocument();
    expect(screen.getByText(/5 years Rust/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /linkedin/i })).toHaveAttribute(
      "href", RESULT.url,
    );
  });

  it("Add button POSTs to /api/jobs/{id}/candidates", async () => {
    let received: unknown;
    server.use(
      http.post("http://localhost:8000/api/jobs/1/candidates", async ({ request }) => {
        received = await request.json();
        return HttpResponse.json({ application_id: 99 }, { status: 202 });
      }),
    );
    const Wrapper = wrap();
    render(<Wrapper><SearchResultCard result={RESULT} jobId={1} /></Wrapper>);
    fireEvent.click(screen.getByRole("button", { name: /add/i }));
    await waitFor(() => expect(received).toEqual({ kind: "url", url: RESULT.url }));
  });
});
```

- [ ] **Step 2: Run, verify fail**

Run: `cd recruiter-frontend && npm run test -- src/components/applications/search-result-card.test.tsx`
Expected: FAIL — file doesn't exist.

- [ ] **Step 3: Implement**

Create `recruiter-frontend/src/components/applications/search-result-card.tsx`:

```tsx
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

const SOURCE_GLYPH: Record<SearchResult["source"], string> = {
  linkedin: "in",
  github: "gh",
  web: "🌐",
};

export function SearchResultCard({ result, jobId }: Props) {
  const qc = useQueryClient();
  const add = useMutation({
    mutationFn: () =>
      api(`/api/jobs/${jobId}/candidates`, {
        method: "POST",
        json: { kind: "url", url: result.url },
      }),
    onSuccess: () => {
      toast.success("Added to pipeline");
      qc.invalidateQueries({ queryKey: queryKeys.jobApplications(jobId) });
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "Add failed");
    },
  });

  return (
    <div className="border rounded p-2 space-y-1 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-sm">{result.name}</span>
        <span className="text-muted-foreground uppercase text-[10px]">
          {SOURCE_GLYPH[result.source]} {result.source}
        </span>
      </div>
      <p className="text-muted-foreground line-clamp-2">{result.snippet}</p>
      <div className="flex items-center justify-between">
        <a
          href={result.url}
          target="_blank"
          rel="noreferrer"
          className="underline truncate max-w-[200px]"
          aria-label={`open ${result.source} profile`}
        >
          {result.url}
        </a>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => add.mutate()}
          disabled={add.isPending}
        >
          {add.isPending ? "Adding…" : "Add"}
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run, verify pass**

Run: `cd recruiter-frontend && npm run test -- src/components/applications/search-result-card.test.tsx`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/walidboudiche/recruiter-agent
git add recruiter-frontend/src/components/applications/search-result-card.tsx \
        recruiter-frontend/src/components/applications/search-result-card.test.tsx
git commit -m "feat(frontend): SearchResultCard with Add → POST /candidates"
```

---

## Task 9: Frontend — chat-panel renders tool.search_results

**Files:**
- Modify: `recruiter-frontend/src/components/applications/chat-panel.tsx`
- Modify: `recruiter-frontend/src/components/applications/chat-panel.test.tsx`

The chat-panel currently consumes NDJSON event types: `message`, `message_delta`, `message_done`, `tool_call_start`, `tool_call_result`, `error`. We add handling for `tool.search_results`.

- [ ] **Step 1: Write the failing test**

Append to `recruiter-frontend/src/components/applications/chat-panel.test.tsx`:

```tsx
// Append at the bottom (use existing imports if present).
import { http, HttpResponse } from "msw";  // already imported above; remove duplicate

describe("ChatPanel — tool.search_results", () => {
  it("renders SearchResultCards inline when the stream emits tool.search_results", async () => {
    server.use(
      http.post("http://localhost:8000/api/applications/42/chat", () => {
        const ndjson = [
          { type: "message", role: "user", id: 1, content: "find rust devs" },
          {
            type: "tool.search_results",
            tool_name: "search_linkedin",
            source: "linkedin",
            results: [{
              name: "Alice Doe",
              url: "https://www.linkedin.com/in/alice/",
              snippet: "Rust dev",
              source: "linkedin",
            }],
          },
          { type: "message_delta", text: "Found 1." },
          { type: "message_done", id: 2 },
        ].map((e) => JSON.stringify(e)).join("\n");
        return new HttpResponse(ndjson, {
          headers: { "content-type": "application/x-ndjson" },
        });
      }),
    );
    // Mount the panel against application 42 — assumes a job_id is reachable
    // via the application; in the test, stub useApplication to return job_id=1.
    // Use the existing pattern in chat-panel.test.tsx for setup; add assertions:
    // - After sending a message, screen.getByText("Alice Doe") appears
    // - The "Add" button is present
  });
});
```

(Adapt the test to the existing scaffolding in `chat-panel.test.tsx`. If that file uses a `renderChatPanel(applicationId, jobId)` helper, follow it. The key assertion: after streaming, `Alice Doe` is rendered.)

- [ ] **Step 2: Run, verify fail**

Run: `cd recruiter-frontend && npm run test -- src/components/applications/chat-panel.test.tsx`
Expected: FAIL — `Alice Doe` not in DOM (chat-panel ignores unknown event types).

- [ ] **Step 3: Implement**

Edit `recruiter-frontend/src/components/applications/chat-panel.tsx`. The panel renders messages from a state variable shaped like:

```ts
type Msg = { id: string; role: "user" | "assistant"; content: string; cards?: SearchResult[] };
```

Find the NDJSON reducer in `useChat` (or wherever the stream is consumed). It dispatches by `event.type`. Add a branch:

```ts
if (event.type === "tool.search_results") {
  // Attach the result cards to the in-progress assistant message,
  // creating one if needed.
  setMessages((prev) => {
    const last = prev[prev.length - 1];
    if (last && last.role === "assistant") {
      return [...prev.slice(0, -1), {
        ...last,
        cards: [...(last.cards ?? []), ...event.results],
      }];
    }
    return [...prev, {
      id: `cards-${Date.now()}`,
      role: "assistant",
      content: "",
      cards: event.results,
    }];
  });
}
```

In the JSX where assistant messages render, add after the message text:

```tsx
{m.cards?.length ? (
  <div className="space-y-1 mt-2">
    {m.cards.map((c) => (
      <SearchResultCard key={c.url} result={c} jobId={jobId} />
    ))}
  </div>
) : null}
```

Add the import: `import { SearchResultCard, type SearchResult } from "./search-result-card";`. The `jobId` prop must be threaded through to ChatPanel — if it isn't already, add it to props and pass it from `application-detail.tsx` (it has `application.data.job_id` from the loaded application).

- [ ] **Step 4: Update application-detail to pass jobId**

Edit `recruiter-frontend/src/routes/application-detail.tsx`. Find the `<ChatPanel applicationId={id} />` line and change it to:

```tsx
<ChatPanel applicationId={id} jobId={application.data.job_id} />
```

- [ ] **Step 5: Run, verify pass**

Run: `cd recruiter-frontend && npm run test`
Expected: full suite green (28 + new tests).

Run: `cd recruiter-frontend && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add recruiter-frontend/src/components/applications/chat-panel.tsx \
        recruiter-frontend/src/components/applications/chat-panel.test.tsx \
        recruiter-frontend/src/routes/application-detail.tsx
git commit -m "feat(frontend): chat-panel renders tool.search_results cards inline"
```

---

## Task 10: Frontend — Sourcing settings tab

**Files:**
- Create: `recruiter-frontend/src/components/settings/sourcing-tab.tsx`
- Modify: `recruiter-frontend/src/routes/settings.tsx`
- Modify: `recruiter-frontend/src/hooks/use-settings.ts` (extend type)

- [ ] **Step 1: Extend the settings type**

Edit `recruiter-frontend/src/hooks/use-settings.ts`. Find the `SettingsRead` interface and add four fields:

```ts
  search_provider: string | null;
  search_engine_id: string | null;
  has_search_api_key: boolean;
  has_github_token: boolean;
```

If `SettingsUpdate` is also typed in this file (or in api-types.ts), add: `search_provider`, `search_api_key`, `search_engine_id`, `github_token`.

- [ ] **Step 2: Implement the tab**

Create `recruiter-frontend/src/components/settings/sourcing-tab.tsx`:

```tsx
import { useState } from "react";
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
import { useSettings, useUpdateSettings } from "@/hooks/use-settings";

export function SourcingTab() {
  const settings = useSettings();
  const update = useUpdateSettings();
  const [provider, setProvider] = useState<string | undefined>();
  const [apiKey, setApiKey] = useState("");
  const [cseId, setCseId] = useState<string | undefined>();
  const [ghToken, setGhToken] = useState("");

  if (settings.isLoading) return <p>Loading…</p>;
  if (!settings.data) return <p>No settings.</p>;

  const cur = settings.data;
  const effProvider = provider ?? cur.search_provider ?? "google_cse";
  const effCse = cseId ?? cur.search_engine_id ?? "";

  function save() {
    const body: Record<string, unknown> = {};
    if (provider !== undefined && provider !== cur.search_provider)
      body.search_provider = provider;
    if (apiKey) body.search_api_key = apiKey;
    if (cseId !== undefined && cseId !== (cur.search_engine_id ?? ""))
      body.search_engine_id = cseId;
    if (ghToken) body.github_token = ghToken;
    update.mutate(body, {
      onSuccess: () => {
        setApiKey("");
        setGhToken("");
      },
    });
  }

  return (
    <div className="space-y-4 max-w-md">
      <div className="space-y-2">
        <Label>Provider (LinkedIn + Web search)</Label>
        <Select value={effProvider} onValueChange={setProvider}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="google_cse">Google Custom Search</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">
          Configure a Custom Search Engine at{" "}
          <a className="underline" href="https://cse.google.com" target="_blank" rel="noreferrer">cse.google.com</a>{" "}
          and enable the Custom Search API in Google Cloud Console.
        </p>
      </div>

      <div className="space-y-2">
        <Label>API key</Label>
        <Input
          type="password"
          placeholder={cur.has_search_api_key ? "•••••• (set)" : "AIza…"}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
      </div>

      <div className="space-y-2">
        <Label>CSE ID (cx)</Label>
        <Input
          placeholder="abcd1234:efgh5678"
          value={effCse}
          onChange={(e) => setCseId(e.target.value)}
        />
      </div>

      <div className="space-y-2">
        <Label>GitHub personal access token (optional)</Label>
        <Input
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

- [ ] **Step 3: Wire it into the Settings page**

Edit `recruiter-frontend/src/routes/settings.tsx`:

```tsx
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LlmTab } from "@/components/settings/llm-tab";
import { NotificationsTab } from "@/components/settings/notifications-tab";
import { ProfileTab } from "@/components/settings/profile-tab";
import { SourcingTab } from "@/components/settings/sourcing-tab";

export default function Settings() {
  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">Settings</h2>
      <Tabs defaultValue="llm">
        <TabsList>
          <TabsTrigger value="llm">LLM</TabsTrigger>
          <TabsTrigger value="notifications">Notifications</TabsTrigger>
          <TabsTrigger value="sourcing">Sourcing</TabsTrigger>
          <TabsTrigger value="profile">Profile</TabsTrigger>
        </TabsList>
        <TabsContent value="llm" className="pt-6"><LlmTab /></TabsContent>
        <TabsContent value="notifications" className="pt-6"><NotificationsTab /></TabsContent>
        <TabsContent value="sourcing" className="pt-6"><SourcingTab /></TabsContent>
        <TabsContent value="profile" className="pt-6"><ProfileTab /></TabsContent>
      </Tabs>
    </div>
  );
}
```

- [ ] **Step 4: Verify the suite**

Run: `cd recruiter-frontend && npm run test`
Expected: green.

Run: `cd recruiter-frontend && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add recruiter-frontend/src/components/settings/sourcing-tab.tsx \
        recruiter-frontend/src/routes/settings.tsx \
        recruiter-frontend/src/hooks/use-settings.ts
git commit -m "feat(frontend): Sourcing settings tab — provider, key, CSE ID, github token"
```

---

## Final verification

After all 10 tasks:

- [ ] Backend: `.venv/bin/pytest -q` → ~221+ pass, mypy clean
- [ ] Frontend: `cd recruiter-frontend && npm run test` → ~30+ pass, tsc clean
- [ ] Manual: in dev (with real Google CSE creds set in Settings), open chat for an application, ask "find me 5 rust engineers in Berlin" — see cards stream in, click Add on one, verify the application appears on the kanban with the appropriate auto-extract or paste-needed state.

## Known v1 limitations (per design)

- Single concrete provider: Google CSE. Slot for SerpAPI / Brave / Tavily exists in the registry but unimplemented.
- No de-duplication when "Add" creates a candidate already in the same job (creates a duplicate row; document in SMOKE.md).
- No separate cost cap for search queries.
- No "Test connection" button in Settings.
