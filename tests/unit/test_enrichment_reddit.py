import httpx
import pytest

from recruiter.enrichment.provider import EnrichmentHint
from recruiter.enrichment.reddit import RedditProvider


def _make_provider(transport: httpx.MockTransport) -> RedditProvider:
    return RedditProvider(transport=transport)


def _about(karma: int = 1234) -> dict:
    return {
        "data": {
            "name": "alice",
            "link_karma": karma,
            "comment_karma": 567,
            "created_utc": 1577836800.0,  # 2020-01-01
            "subreddit": {"public_description": "Software engineer"},
        }
    }


def _comments(items: list[dict] | None = None) -> dict:
    return {
        "data": {
            "children": [
                {"data": item}
                for item in (items or [])
            ]
        }
    }


@pytest.mark.asyncio
async def test_enrich_returns_signals_for_known_user() -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        if req.url.path.endswith("/about.json"):
            return httpx.Response(200, json=_about())
        if req.url.path.endswith("/comments.json"):
            return httpx.Response(200, json=_comments([
                {"body": "Use tokio for async Rust", "subreddit": "rust",
                 "permalink": "/r/rust/c/1", "created_utc": 1700000000.0, "score": 12},
                {"body": "Postgres beats MySQL for OLTP", "subreddit": "Database",
                 "permalink": "/r/Database/c/2", "created_utc": 1700001000.0, "score": 5},
            ]))
        return httpx.Response(404)

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.reddit.com/user/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert r.source == "reddit"
    assert r.profile_url == "https://www.reddit.com/user/alice"
    assert r.confidence == 1.0
    assert any("/about.json" in p_ for p_ in paths)
    assert any("/comments.json" in p_ for p_ in paths)
    # Public bio + 2 comments → at least 2 signals.
    assert len(r.signals) >= 2


@pytest.mark.asyncio
async def test_enrich_returns_none_on_404() -> None:
    handler = lambda req: httpx.Response(404, text="not found")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://reddit.com/u/ghost", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_handles_old_reddit_url_form() -> None:
    """old.reddit.com/u/<u> should resolve the same username."""
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/about.json"):
            return httpx.Response(200, json=_about())
        return httpx.Response(200, json=_comments([]))

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://old.reddit.com/u/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert "alice" in r.profile_url


@pytest.mark.asyncio
async def test_enrich_returns_none_on_429() -> None:
    handler = lambda req: httpx.Response(429, text="rate")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.reddit.com/u/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_5xx() -> None:
    handler = lambda req: httpx.Response(503, text="oops")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.reddit.com/u/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_network_failure() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.reddit.com/u/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_propagates_low_confidence_hint() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/about.json"):
            return httpx.Response(200, json=_about())
        return httpx.Response(200, json=_comments([
            {"body": "x", "subreddit": "x", "permalink": "/r/x/1", "created_utc": 1.0, "score": 0}
        ]))

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.reddit.com/u/alice", confidence=0.5)
    r = await p.enrich(hint)
    assert r is not None and r.confidence == 0.5 and r.discovered


@pytest.mark.asyncio
async def test_enrich_caps_signals_at_5() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/about.json"):
            return httpx.Response(200, json=_about())
        return httpx.Response(200, json=_comments([
            {"body": f"comment {i}", "subreddit": "x", "permalink": f"/r/x/{i}",
             "created_utc": 1.0, "score": 0}
            for i in range(20)
        ]))

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.reddit.com/u/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert len(r.signals) <= 5


@pytest.mark.asyncio
async def test_enrich_with_name_only_hint_returns_none() -> None:
    handler = lambda req: httpx.Response(200, json={})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(name="Alice Doe", confidence=0.5)
    assert await p.enrich(hint) is None
