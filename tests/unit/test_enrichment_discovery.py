import pytest

from recruiter.enrichment.discovery import discover
from recruiter.sourcing.provider import SearchError, SearchResult


class FakeSourcing:
    """Stand-in for a SourcingProvider. Records every query."""
    def __init__(self, results_by_query: dict[str, list[SearchResult]] | None = None,
                 raise_for: dict[str, Exception] | None = None) -> None:
        self.queries: list[tuple[str, int]] = []
        self._results = results_by_query or {}
        self._raise = raise_for or {}

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        self.queries.append((query, limit))
        if query in self._raise:
            raise self._raise[query]
        return self._results.get(query, [])


def _registry_with(*provider_classes):
    """Helper: replaces the enrichment registry for one test."""
    from recruiter.enrichment.provider import _REGISTRY
    saved = dict(_REGISTRY)
    _REGISTRY.clear()
    for cls in provider_classes:
        _REGISTRY[cls.name] = cls
    return saved


def _restore(saved):
    from recruiter.enrichment.provider import _REGISTRY
    _REGISTRY.clear()
    _REGISTRY.update(saved)


class _MastoProvider:
    name = "mastodon"
    domains = ["mastodon.social", "fosstodon.org"]
    def __init__(self, *_, **__): pass
    async def enrich(self, hint): return None
    async def aclose(self): pass


class _GitHubProvider:
    name = "github"
    domains = ["github.com"]
    def __init__(self, *_, **__): pass
    async def enrich(self, hint): return None
    async def aclose(self): pass


@pytest.mark.asyncio
async def test_discover_issues_one_query_per_provider_domain_pair() -> None:
    saved = _registry_with(_MastoProvider, _GitHubProvider)
    try:
        sourcing = FakeSourcing()
        fake_settings = type("S", (), {
            "enrichment_sources": {},
            "github_token_enc": None,
            "enrichment_twitter_api_key_enc": None,
            "enrichment_youtube_api_key_enc": None,
            "enrichment_stackexchange_key_enc": None,
        })()
        await discover(
            name="Alice Doe",
            employer="Acme",
            sourcing=sourcing,
            settings=fake_settings,
        )
        # 2 mastodon domains + 1 github domain = 3 queries.
        assert len(sourcing.queries) == 3
        for q, _ in sourcing.queries:
            assert '"Alice Doe"' in q
            assert '"Acme"' in q
            assert "site:" in q
    finally:
        _restore(saved)


@pytest.mark.asyncio
async def test_discover_returns_hints_at_confidence_0_5() -> None:
    saved = _registry_with(_GitHubProvider)
    try:
        sourcing = FakeSourcing(results_by_query={
            '"Alice" "Acme" site:github.com': [
                SearchResult(name="Alice", url="https://github.com/alice",
                             snippet="rust dev", source="web"),
            ]
        })
        fake_settings = type("S", (), {"enrichment_sources": {}, "github_token_enc": None})()
        hints = await discover("Alice", "Acme", sourcing=sourcing, settings=fake_settings)
        assert len(hints) == 1
        assert hints[0].confidence == 0.5
        assert hints[0].url == "https://github.com/alice"
        assert hints[0].source == "github"
    finally:
        _restore(saved)


@pytest.mark.asyncio
async def test_discover_skips_disabled_sources() -> None:
    saved = _registry_with(_MastoProvider, _GitHubProvider)
    try:
        sourcing = FakeSourcing()
        fake_settings = type("S", (), {
            "enrichment_sources": {"mastodon": False},
            "github_token_enc": None,
        })()
        await discover("Alice", "Acme", sourcing=sourcing, settings=fake_settings)
        # Only github queries should fire.
        assert all("github.com" in q for q, _ in sourcing.queries)
    finally:
        _restore(saved)


@pytest.mark.asyncio
async def test_discover_returns_empty_when_sourcing_none() -> None:
    """No active sourcing provider → no discovery (no errors raised)."""
    hints = await discover("Alice", "Acme", sourcing=None, settings=type("S", (), {})())
    assert hints == []


@pytest.mark.asyncio
async def test_discover_skips_query_when_sourcing_raises() -> None:
    saved = _registry_with(_GitHubProvider)
    try:
        sourcing = FakeSourcing(raise_for={
            '"Alice" "Acme" site:github.com': SearchError("rate limit", transient=True)
        })
        fake_settings = type("S", (), {"enrichment_sources": {}, "github_token_enc": None})()
        hints = await discover("Alice", "Acme", sourcing=sourcing, settings=fake_settings)
        # Failure is non-fatal: just no hint for that domain.
        assert hints == []
    finally:
        _restore(saved)


@pytest.mark.asyncio
async def test_discover_takes_only_top_result_per_domain() -> None:
    saved = _registry_with(_GitHubProvider)
    try:
        sourcing = FakeSourcing(results_by_query={
            '"Alice" "Acme" site:github.com': [
                SearchResult(
                    name="Alice", url="https://github.com/alice",
                    snippet="", source="web",
                ),
                SearchResult(
                    name="Other Alice", url="https://github.com/other",
                    snippet="", source="web",
                ),
            ]
        })
        fake_settings = type("S", (), {"enrichment_sources": {}, "github_token_enc": None})()
        hints = await discover("Alice", "Acme", sourcing=sourcing, settings=fake_settings)
        assert len(hints) == 1
        assert hints[0].url == "https://github.com/alice"
    finally:
        _restore(saved)


@pytest.mark.asyncio
async def test_discover_handles_empty_employer() -> None:
    """No employer → query is just '"<name>" site:<domain>'."""
    saved = _registry_with(_GitHubProvider)
    try:
        sourcing = FakeSourcing()
        fake_settings = type("S", (), {"enrichment_sources": {}, "github_token_enc": None})()
        await discover("Alice", "", sourcing=sourcing, settings=fake_settings)
        for q, _ in sourcing.queries:
            assert '"Alice"' in q
            assert '"Acme"' not in q
    finally:
        _restore(saved)


@pytest.mark.asyncio
async def test_discover_skips_blog_provider_with_empty_domains() -> None:
    """BlogProvider has domains=[] — it must not cause a degenerate query."""
    class _Blog:
        name = "blog"
        domains: list[str] = []
        def __init__(self, *_, **__): pass
        async def enrich(self, hint): return None
        async def aclose(self): pass

    saved = _registry_with(_Blog, _GitHubProvider)
    try:
        sourcing = FakeSourcing()
        fake_settings = type("S", (), {"enrichment_sources": {}, "github_token_enc": None})()
        await discover("Alice", "Acme", sourcing=sourcing, settings=fake_settings)
        for q, _ in sourcing.queries:
            assert "site:" in q  # never a degenerate site:<empty>
    finally:
        _restore(saved)
