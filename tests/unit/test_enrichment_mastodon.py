import httpx
import pytest

from recruiter.enrichment.mastodon import MastodonProvider, KNOWN_INSTANCES
from recruiter.enrichment.provider import EnrichmentHint


def _make_provider(transport: httpx.MockTransport) -> MastodonProvider:
    return MastodonProvider(transport=transport)


def _account(id_: str = "42") -> dict:
    return {
        "id": id_,
        "username": "alice",
        "acct": "alice",
        "display_name": "Alice Doe",
        "note": "Software engineer. github.com/alice",
        "url": "https://mastodon.social/@alice",
        "followers_count": 123,
        "statuses_count": 456,
    }


def _status(id_: str, content: str = "<p>Hello</p>", created: str = "2025-04-01T12:00:00Z") -> dict:
    return {
        "id": id_,
        "content": content,
        "url": f"https://mastodon.social/@alice/{id_}",
        "created_at": created,
    }


@pytest.mark.asyncio
async def test_enrich_known_account_returns_signals() -> None:
    seen_paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_paths.append(req.url.path)
        if req.url.path == "/api/v1/accounts/lookup":
            return httpx.Response(200, json=_account())
        if req.url.path == "/api/v1/accounts/42/statuses":
            return httpx.Response(200, json=[
                _status("1", content="<p>Just shipped some Rust async code</p>"),
                _status("2", content="<p>Postgres tip: covering indexes</p>"),
            ])
        return httpx.Response(404)

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://mastodon.social/@alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert r.source == "mastodon"
    assert r.confidence == 1.0
    assert len(r.signals) >= 2
    assert "/api/v1/accounts/lookup" in seen_paths


@pytest.mark.asyncio
async def test_enrich_strips_html_from_status_content() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/v1/accounts/lookup":
            return httpx.Response(200, json=_account())
        return httpx.Response(200, json=[
            _status("1", content="<p>Hello <strong>world</strong></p>"),
        ])
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://mastodon.social/@alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    # No raw HTML tags in any signal summary.
    for s in r.signals:
        assert "<p>" not in s.summary
        assert "<strong>" not in s.summary


@pytest.mark.asyncio
async def test_enrich_unknown_instance_returns_none() -> None:
    handler = lambda req: httpx.Response(200, json=_account())
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://random.example/@alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_lookup_404() -> None:
    handler = lambda req: httpx.Response(404, text="not found")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://mastodon.social/@ghost", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_429() -> None:
    handler = lambda req: httpx.Response(429, text="rate")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://fosstodon.org/@alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_5xx() -> None:
    handler = lambda req: httpx.Response(503, text="bad")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://hachyderm.io/@alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_network_failure() -> None:
    def handler(req): raise httpx.ConnectError("refused", request=req)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://mastodon.social/@alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_caps_signals_at_5() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/v1/accounts/lookup":
            return httpx.Response(200, json=_account())
        return httpx.Response(200, json=[_status(str(i)) for i in range(20)])
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://mastodon.social/@alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None and len(r.signals) <= 5


@pytest.mark.asyncio
async def test_enrich_propagates_low_confidence() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/v1/accounts/lookup":
            return httpx.Response(200, json=_account())
        return httpx.Response(200, json=[_status("1")])
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://mastodon.social/@alice", confidence=0.5)
    r = await p.enrich(hint)
    assert r is not None
    assert r.confidence == 0.5 and r.discovered


def test_known_instances_includes_major_mastodon_servers() -> None:
    assert "mastodon.social" in KNOWN_INSTANCES
    assert "fosstodon.org" in KNOWN_INSTANCES
    assert "hachyderm.io" in KNOWN_INSTANCES
