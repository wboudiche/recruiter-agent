import httpx
import pytest

from recruiter.enrichment.hackernews import HackerNewsProvider
from recruiter.enrichment.provider import EnrichmentHint


def _make_provider(transport: httpx.MockTransport) -> HackerNewsProvider:
    return HackerNewsProvider(transport=transport)


@pytest.mark.asyncio
async def test_enrich_returns_signals_for_known_user() -> None:
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.setdefault("paths", []).append(req.url.path)
        seen.setdefault("queries", []).append(dict(req.url.params))
        if "tags" in req.url.params and "story" in req.url.params["tags"]:
            return httpx.Response(200, json={
                "hits": [
                    {
                        "objectID": "1",
                        "title": "Show HN: my Rust crate",
                        "url": "https://news.ycombinator.com/item?id=1",
                        "created_at": "2025-04-01T12:00:00Z",
                        "points": 42,
                    },
                ],
                "nbHits": 1,
            })
        return httpx.Response(200, json={"hits": [], "nbHits": 0})

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://news.ycombinator.com/user?id=alice", confidence=1.0)
    result = await p.enrich(hint)
    assert result is not None
    assert result.source == "hackernews"
    assert result.profile_url == "https://news.ycombinator.com/user?id=alice"
    assert result.confidence == 1.0
    assert any("Show HN" in s.summary for s in result.signals)
    # Must hit the Algolia search endpoint.
    assert any("hn.algolia.com" in p_ for p_ in [str(req) for req in seen.get("paths", [])]) or any(
        "/api/v1/search" in p_ for p_ in seen.get("paths", [])
    )


@pytest.mark.asyncio
async def test_enrich_returns_none_when_user_has_no_activity() -> None:
    handler = lambda req: httpx.Response(200, json={"hits": [], "nbHits": 0})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://news.ycombinator.com/user?id=ghost", confidence=1.0)
    result = await p.enrich(hint)
    assert result is None


@pytest.mark.asyncio
async def test_enrich_handles_missing_fields_gracefully() -> None:
    handler = lambda req: httpx.Response(200, json={
        "hits": [{"objectID": "x"}],  # no title, no url, no timestamp
        "nbHits": 1,
    })
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://news.ycombinator.com/user?id=alice", confidence=1.0)
    result = await p.enrich(hint)
    # Provider must not crash on partial responses; it can still return a
    # result with a generic signal or skip the malformed item.
    assert result is None or len(result.signals) <= 1


@pytest.mark.asyncio
async def test_enrich_returns_none_on_network_failure() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://news.ycombinator.com/user?id=alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_5xx() -> None:
    handler = lambda req: httpx.Response(503, text="bad")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://news.ycombinator.com/user?id=alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_429() -> None:
    handler = lambda req: httpx.Response(429, text="rate")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://news.ycombinator.com/user?id=alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_caps_signals_at_5() -> None:
    handler = lambda req: httpx.Response(200, json={
        "hits": [
            {"objectID": str(i), "title": f"post {i}", "url": f"https://hn/{i}", "created_at": "2025-01-01T00:00:00Z"}
            for i in range(20)
        ],
        "nbHits": 20,
    })
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://news.ycombinator.com/user?id=alice", confidence=1.0)
    result = await p.enrich(hint)
    assert result is not None
    assert len(result.signals) <= 5


@pytest.mark.asyncio
async def test_enrich_propagates_hint_confidence() -> None:
    handler = lambda req: httpx.Response(200, json={
        "hits": [{"objectID": "1", "title": "x", "url": "https://hn/1", "created_at": "2025-01-01T00:00:00Z"}],
        "nbHits": 1,
    })
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://news.ycombinator.com/user?id=alice", confidence=0.5)
    result = await p.enrich(hint)
    assert result is not None
    assert result.confidence == 0.5
    assert result.discovered  # confidence < 1.0 => discovered


@pytest.mark.asyncio
async def test_enrich_with_name_only_hint_returns_none() -> None:
    """HN provider needs a username; a bare-name discovery hint is unactionable."""
    handler = lambda req: httpx.Response(200, json={"hits": [], "nbHits": 0})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(name="Alice Doe", confidence=0.5)
    assert await p.enrich(hint) is None
