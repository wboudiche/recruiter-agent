import httpx
import pytest

from recruiter.enrichment.provider import EnrichmentHint
from recruiter.enrichment.youtube import YouTubeProvider


def _make_provider(transport: httpx.MockTransport, **kw) -> YouTubeProvider:
    return YouTubeProvider(api_key="ytkey", transport=transport, **kw)


def _channels(channel_id: str = "UC123") -> dict:
    return {
        "items": [{
            "id": channel_id,
            "snippet": {
                "title": "Alice's Channel",
                "description": "Rust talks",
                "customUrl": "@alice",
            },
            "statistics": {
                "subscriberCount": "1500",
                "videoCount": "12",
            },
        }]
    }


def _videos() -> dict:
    return {
        "items": [
            {
                "id": {"videoId": "vid1"},
                "snippet": {
                    "title": "RustConf talk: async lifetimes",
                    "publishedAt": "2025-04-01T12:00:00Z",
                    "description": "Talk at RustConf 2025",
                },
            },
            {
                "id": {"videoId": "vid2"},
                "snippet": {
                    "title": "Postgres internals",
                    "publishedAt": "2025-03-01T12:00:00Z",
                    "description": "Internal architecture",
                },
            },
        ]
    }


@pytest.mark.asyncio
async def test_enrich_known_channel_returns_signals() -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        if req.url.path.endswith("/channels"):
            return httpx.Response(200, json=_channels())
        if req.url.path.endswith("/search"):
            return httpx.Response(200, json=_videos())
        return httpx.Response(404)

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.youtube.com/@alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert r.source == "youtube"
    assert r.confidence == 1.0
    assert "@alice" in r.profile_url
    assert any("RustConf" in s.summary for s in r.signals)
    assert any(s.type == "talk" for s in r.signals)


@pytest.mark.asyncio
async def test_enrich_passes_api_key_in_query() -> None:
    seen_keys: list[str | None] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_keys.append(req.url.params.get("key"))
        if req.url.path.endswith("/channels"):
            return httpx.Response(200, json=_channels())
        return httpx.Response(200, json=_videos())

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.youtube.com/@alice", confidence=1.0)
    await p.enrich(hint)
    assert all(k == "ytkey" for k in seen_keys)


@pytest.mark.asyncio
async def test_enrich_unknown_handle_returns_none() -> None:
    handler = lambda req: httpx.Response(200, json={"items": []})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.youtube.com/@ghost", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_403_quota() -> None:
    handler = lambda req: httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.youtube.com/@alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_400_invalid_key() -> None:
    handler = lambda req: httpx.Response(400, json={"error": {"errors": [{"reason": "keyInvalid"}]}})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.youtube.com/@alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_429() -> None:
    handler = lambda req: httpx.Response(429)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.youtube.com/@alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_5xx() -> None:
    handler = lambda req: httpx.Response(503)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.youtube.com/@alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_network_failure() -> None:
    def handler(req): raise httpx.ConnectError("refused", request=req)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.youtube.com/@alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_caps_signals_at_5() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/channels"):
            return httpx.Response(200, json=_channels())
        return httpx.Response(200, json={
            "items": [
                {"id": {"videoId": f"v{i}"},
                 "snippet": {"title": f"video {i}", "publishedAt": "2025-01-01T00:00:00Z",
                             "description": "x"}}
                for i in range(20)
            ]
        })
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.youtube.com/@alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None and len(r.signals) <= 5


@pytest.mark.asyncio
async def test_enrich_propagates_low_confidence() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/channels"):
            return httpx.Response(200, json=_channels())
        return httpx.Response(200, json=_videos())
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.youtube.com/@alice", confidence=0.5)
    r = await p.enrich(hint)
    assert r is not None and r.confidence == 0.5 and r.discovered
