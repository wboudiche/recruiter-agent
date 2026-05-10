import httpx
import pytest

from recruiter.enrichment.devto import DevToProvider
from recruiter.enrichment.provider import EnrichmentHint


def _make_provider(transport: httpx.MockTransport) -> DevToProvider:
    return DevToProvider(transport=transport)


def _user() -> dict:
    return {
        "username": "alice",
        "name": "Alice Doe",
        "summary": "Rust developer",
        "website_url": "https://alice.dev",
        "twitter_username": "alice",
        "github_username": "alice",
    }


def _articles(n: int = 2) -> list[dict]:
    return [
        {
            "id": i + 1,
            "title": f"Async Rust tip #{i+1}",
            "url": f"https://dev.to/alice/async-rust-tip-{i+1}",
            "published_at": "2025-04-01T00:00:00Z",
            "tag_list": ["rust", "async"],
            "positive_reactions_count": 10 + i,
        }
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_enrich_known_user_returns_signals() -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        if req.url.path == "/api/users/by_username":
            return httpx.Response(200, json=_user())
        if req.url.path == "/api/articles":
            return httpx.Response(200, json=_articles(3))
        return httpx.Response(404)

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://dev.to/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert r.source == "devto"
    assert r.profile_url == "https://dev.to/alice"
    assert r.confidence == 1.0
    assert any("Async Rust" in s.summary for s in r.signals)


@pytest.mark.asyncio
async def test_enrich_user_not_found_returns_none() -> None:
    handler = lambda req: httpx.Response(404, text="not found")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://dev.to/ghost", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_handles_no_articles() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/users/by_username":
            return httpx.Response(200, json=_user())
        return httpx.Response(200, json=[])
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://dev.to/alice", confidence=1.0)
    r = await p.enrich(hint)
    # No articles but a real profile → still emits a profile-only signal.
    assert r is not None
    assert any(s.type == "profile" for s in r.signals)


@pytest.mark.asyncio
async def test_enrich_returns_none_on_5xx() -> None:
    handler = lambda req: httpx.Response(503)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://dev.to/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_429() -> None:
    handler = lambda req: httpx.Response(429)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://dev.to/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_network_failure() -> None:
    def handler(req): raise httpx.ConnectError("refused", request=req)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://dev.to/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_caps_signals_at_5() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/users/by_username":
            return httpx.Response(200, json=_user())
        return httpx.Response(200, json=_articles(20))
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://dev.to/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None and len(r.signals) <= 5


@pytest.mark.asyncio
async def test_enrich_propagates_low_confidence() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/users/by_username":
            return httpx.Response(200, json=_user())
        return httpx.Response(200, json=_articles(2))
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://dev.to/alice", confidence=0.5)
    r = await p.enrich(hint)
    assert r is not None and r.confidence == 0.5 and r.discovered


@pytest.mark.asyncio
async def test_enrich_with_name_only_hint_returns_none() -> None:
    handler = lambda req: httpx.Response(200, json={})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(name="Alice Doe", confidence=0.5)
    assert await p.enrich(hint) is None
