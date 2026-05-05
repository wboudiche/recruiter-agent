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
    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _s: fake)
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
    # source on individual cards is overridden by the tool wrapper from "web" -> "linkedin".
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
    assert "isn't configured" in result["summary"].lower() or "not configured" in result["summary"].lower()
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
    """search_github bypasses the provider registry and uses GitHubSearchClient
    directly. With no github_token configured it still works (anonymous)."""
    captured: dict = {}

    class _FakeGH:
        def __init__(self, *, token, transport=None) -> None:
            captured["token"] = token

        async def search_users(self, q, limit):
            return [SearchResult(name="alice", url="https://github.com/alice",
                                 snippet="x", source="github")]

        async def aclose(self): pass

    import recruiter.agent.tools as tools_mod
    import recruiter.sourcing.search as search_mod
    async def _load_settings(_session): return fake_settings  # github_token_enc=None
    monkeypatch.setattr(tools_mod, "_load_settings_for_tool", _load_settings)
    monkeypatch.setattr(search_mod, "GitHubSearchClient", _FakeGH)

    ctx = ToolContext(session=None, application_id=1, undo_store=None)  # type: ignore[arg-type]
    handler = get_tool_handler("search_github")
    result = await handler(ctx, {"query": "rust"})
    assert "alice" in result["summary"]
    assert captured["token"] is None  # no token configured = anonymous fine
    assert ctx.frontend_events[0]["source"] == "github"


@pytest.mark.asyncio
async def test_search_linkedin_empty_results_does_not_emit_event(
    fake_settings, monkeypatch,
) -> None:
    """A provider returning [] must produce 'No results found.' for the LLM
    AND not push an empty card stack to the frontend."""
    fake = _FakeProvider(results=[])
    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _s: fake)
    import recruiter.agent.tools as tools_mod
    async def _load_settings(_session): return fake_settings
    monkeypatch.setattr(tools_mod, "_load_settings_for_tool", _load_settings)

    ctx = ToolContext(session=None, application_id=1, undo_store=None)  # type: ignore[arg-type]
    handler = get_tool_handler("search_linkedin")
    result = await handler(ctx, {"query": "zzznoresults"})
    assert result["summary"] == "No results found."
    assert ctx.frontend_events == []
