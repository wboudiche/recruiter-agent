import httpx
import pytest

from recruiter.enrichment.provider import EnrichmentHint
from recruiter.enrichment.twitter import TwitterProvider


def _make_provider(transport: httpx.MockTransport, **kw) -> TwitterProvider:
    return TwitterProvider(bearer_token="bearer-xxx", transport=transport, **kw)


def _user(uid: str = "777") -> dict:
    return {
        "data": {
            "id": uid,
            "username": "alice",
            "name": "Alice Doe",
            "description": "Rust + Postgres",
            "public_metrics": {"followers_count": 5000, "tweet_count": 4321},
            "url": "https://alice.dev",
        }
    }


def _tweets() -> dict:
    return {
        "data": [
            {"id": "t1", "text": "Just shipped a Rust crate.",
             "created_at": "2025-04-01T12:00:00.000Z",
             "public_metrics": {"like_count": 100, "retweet_count": 20, "reply_count": 5, "quote_count": 1}},
            {"id": "t2", "text": "Postgres tip: covering indexes.",
             "created_at": "2025-04-02T12:00:00.000Z",
             "public_metrics": {"like_count": 40, "retweet_count": 8, "reply_count": 2, "quote_count": 0}},
        ]
    }


@pytest.mark.asyncio
async def test_enrich_known_user_returns_signals() -> None:
    seen_auth: list[str | None] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_auth.append(req.headers.get("Authorization"))
        if "/users/by/username/" in req.url.path:
            return httpx.Response(200, json=_user())
        if "/users/777/tweets" in req.url.path:
            return httpx.Response(200, json=_tweets())
        return httpx.Response(404)

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://twitter.com/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert r.source == "twitter"
    assert r.confidence == 1.0
    assert any("Rust" in s.summary for s in r.signals)
    assert all(a == "Bearer bearer-xxx" for a in seen_auth if a)


@pytest.mark.asyncio
async def test_enrich_handles_x_dot_com_url_form() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/users/by/username/" in req.url.path:
            return httpx.Response(200, json=_user())
        return httpx.Response(200, json=_tweets())
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://x.com/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_user_not_found() -> None:
    handler = lambda req: httpx.Response(404, json={"errors": [{"detail": "Not Found"}]})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://twitter.com/ghost", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_401() -> None:
    handler = lambda req: httpx.Response(401, json={"title": "Unauthorized"})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://twitter.com/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_429_quota() -> None:
    handler = lambda req: httpx.Response(429, json={"title": "Too Many Requests"})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://twitter.com/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_5xx() -> None:
    handler = lambda req: httpx.Response(503)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://twitter.com/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_network_failure() -> None:
    def handler(req): raise httpx.ConnectError("refused", request=req)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://twitter.com/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_caps_signals_at_5() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/users/by/username/" in req.url.path:
            return httpx.Response(200, json=_user())
        return httpx.Response(200, json={
            "data": [
                {"id": f"t{i}", "text": f"tweet {i}",
                 "created_at": "2025-01-01T00:00:00.000Z",
                 "public_metrics": {"like_count": 1, "retweet_count": 0, "reply_count": 0, "quote_count": 0}}
                for i in range(20)
            ]
        })
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://twitter.com/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None and len(r.signals) <= 5


@pytest.mark.asyncio
async def test_enrich_propagates_low_confidence() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/users/by/username/" in req.url.path:
            return httpx.Response(200, json=_user())
        return httpx.Response(200, json=_tweets())
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://x.com/alice", confidence=0.5)
    r = await p.enrich(hint)
    assert r is not None and r.confidence == 0.5 and r.discovered


@pytest.mark.asyncio
async def test_enrich_with_name_only_hint_returns_none() -> None:
    handler = lambda req: httpx.Response(200, json={})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(name="Alice Doe", confidence=0.5)
    assert await p.enrich(hint) is None
