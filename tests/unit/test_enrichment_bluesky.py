import httpx
import pytest

from recruiter.enrichment.bluesky import BlueskyProvider
from recruiter.enrichment.provider import EnrichmentHint


def _make_provider(transport: httpx.MockTransport) -> BlueskyProvider:
    return BlueskyProvider(transport=transport)


def _profile() -> dict:
    return {
        "did": "did:plc:alice",
        "handle": "alice.bsky.social",
        "displayName": "Alice Doe",
        "description": "Rust + Postgres engineer",
        "followersCount": 200,
        "postsCount": 1500,
    }


def _feed(items: list[dict] | None = None) -> dict:
    return {"feed": [{"post": item} for item in (items or [])]}


@pytest.mark.asyncio
async def test_enrich_known_profile_returns_signals() -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        if req.url.path.endswith("getProfile"):
            return httpx.Response(200, json=_profile())
        if req.url.path.endswith("getAuthorFeed"):
            return httpx.Response(200, json=_feed([
                {"uri": "at://did:plc:alice/app.bsky.feed.post/1",
                 "record": {"text": "Just shipped a Rust crate", "createdAt": "2025-04-01T12:00:00Z"},
                 "indexedAt": "2025-04-01T12:00:00Z"},
                {"uri": "at://did:plc:alice/app.bsky.feed.post/2",
                 "record": {"text": "Postgres tip of the day", "createdAt": "2025-04-02T12:00:00Z"},
                 "indexedAt": "2025-04-02T12:00:00Z"},
            ]))
        return httpx.Response(404)

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://bsky.app/profile/alice.bsky.social", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert r.source == "bluesky"
    assert r.profile_url == "https://bsky.app/profile/alice.bsky.social"
    assert r.confidence == 1.0
    assert any("getProfile" in p_ for p_ in paths)
    assert any("getAuthorFeed" in p_ for p_ in paths)
    assert any("Rust" in s.summary for s in r.signals)


@pytest.mark.asyncio
async def test_enrich_returns_none_on_unknown_handle() -> None:
    handler = lambda req: httpx.Response(400, text="Profile not found")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://bsky.app/profile/ghost.bsky.social", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_5xx() -> None:
    handler = lambda req: httpx.Response(503)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://bsky.app/profile/alice.bsky.social", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_429() -> None:
    handler = lambda req: httpx.Response(429)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://bsky.app/profile/alice.bsky.social", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_network_failure() -> None:
    def handler(req): raise httpx.ConnectError("refused", request=req)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://bsky.app/profile/alice.bsky.social", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_handles_empty_feed() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("getProfile"):
            return httpx.Response(200, json=_profile())
        return httpx.Response(200, json=_feed([]))
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://bsky.app/profile/alice.bsky.social", confidence=1.0)
    r = await p.enrich(hint)
    # With empty feed but a real profile, the provider should still emit a
    # profile-only signal.
    assert r is not None
    assert any(s.type == "profile" for s in r.signals)


@pytest.mark.asyncio
async def test_enrich_caps_signals_at_5() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("getProfile"):
            return httpx.Response(200, json=_profile())
        return httpx.Response(200, json=_feed([
            {"uri": f"at://x/{i}",
             "record": {"text": f"post {i}", "createdAt": "2025-01-01T00:00:00Z"},
             "indexedAt": "2025-01-01T00:00:00Z"}
            for i in range(20)
        ]))
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://bsky.app/profile/alice.bsky.social", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None and len(r.signals) <= 5


@pytest.mark.asyncio
async def test_enrich_propagates_low_confidence() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("getProfile"):
            return httpx.Response(200, json=_profile())
        return httpx.Response(200, json=_feed([
            {"uri": "at://x/1", "record": {"text": "x", "createdAt": "2025-01-01T00:00:00Z"},
             "indexedAt": "2025-01-01T00:00:00Z"}
        ]))
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://bsky.app/profile/alice.bsky.social", confidence=0.5)
    r = await p.enrich(hint)
    assert r is not None and r.confidence == 0.5 and r.discovered


@pytest.mark.asyncio
async def test_enrich_with_name_only_hint_returns_none() -> None:
    handler = lambda req: httpx.Response(200, json={})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(name="Alice Doe", confidence=0.5)
    assert await p.enrich(hint) is None
