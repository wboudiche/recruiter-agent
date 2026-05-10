import httpx
import pytest

from recruiter.enrichment.provider import EnrichmentHint
from recruiter.enrichment.stackoverflow import StackOverflowProvider


def _make_provider(transport: httpx.MockTransport, **kw) -> StackOverflowProvider:
    return StackOverflowProvider(transport=transport, **kw)


def _user_resp() -> dict:
    return {
        "items": [{
            "user_id": 12345,
            "display_name": "Alice Doe",
            "reputation": 5400,
            "link": "https://stackoverflow.com/users/12345/alice-doe",
            "about_me": "<p>Rust dev</p>",
        }]
    }


def _answers_resp() -> dict:
    return {
        "items": [
            {
                "answer_id": 1, "question_id": 100,
                "score": 25, "is_accepted": True,
                "creation_date": 1700000000,
                "tags": ["rust", "async"],
                "link": "https://stackoverflow.com/a/1",
            },
            {
                "answer_id": 2, "question_id": 101,
                "score": 8, "is_accepted": False,
                "creation_date": 1701000000,
                "link": "https://stackoverflow.com/a/2",
            },
        ]
    }


@pytest.mark.asyncio
async def test_enrich_known_user_returns_signals() -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        if "/users/12345/answers" in req.url.path:
            return httpx.Response(200, json=_answers_resp())
        if "/users/12345" in req.url.path:
            return httpx.Response(200, json=_user_resp())
        return httpx.Response(404)

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://stackoverflow.com/users/12345/alice-doe", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert r.source == "stackoverflow"
    assert r.profile_url == "https://stackoverflow.com/users/12345/alice-doe"
    assert any(s.type == "answer" for s in r.signals)
    assert any("rep" in r.summary.lower() or "reputation" in r.summary.lower() for _ in [0])


@pytest.mark.asyncio
async def test_enrich_passes_api_key_when_provided() -> None:
    seen_params: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_params.append(dict(req.url.params))
        if "/users/12345/answers" in req.url.path:
            return httpx.Response(200, json={"items": []})
        return httpx.Response(200, json=_user_resp())

    p = _make_provider(httpx.MockTransport(handler), api_key="test-key")
    hint = EnrichmentHint(url="https://stackoverflow.com/users/12345/alice", confidence=1.0)
    await p.enrich(hint)
    # Both requests should include the key.
    for params in seen_params:
        assert params.get("key") == "test-key"


@pytest.mark.asyncio
async def test_enrich_user_not_found_returns_none() -> None:
    handler = lambda req: httpx.Response(200, json={"items": []})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://stackoverflow.com/users/99999/ghost", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_404() -> None:
    handler = lambda req: httpx.Response(404)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://stackoverflow.com/users/12345/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_429() -> None:
    handler = lambda req: httpx.Response(429)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://stackoverflow.com/users/12345/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_5xx() -> None:
    handler = lambda req: httpx.Response(503)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://stackoverflow.com/users/12345/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_network_failure() -> None:
    def handler(req): raise httpx.ConnectError("refused", request=req)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://stackoverflow.com/users/12345/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_caps_signals_at_5() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/answers" in req.url.path:
            return httpx.Response(200, json={
                "items": [
                    {"answer_id": i, "question_id": i+1000, "score": 1,
                     "is_accepted": False, "creation_date": 1700000000,
                     "link": f"https://stackoverflow.com/a/{i}"}
                    for i in range(20)
                ]
            })
        return httpx.Response(200, json=_user_resp())
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://stackoverflow.com/users/12345/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None and len(r.signals) <= 5


@pytest.mark.asyncio
async def test_enrich_propagates_low_confidence() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/answers" in req.url.path:
            return httpx.Response(200, json=_answers_resp())
        return httpx.Response(200, json=_user_resp())
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://stackoverflow.com/users/12345/alice", confidence=0.5)
    r = await p.enrich(hint)
    assert r is not None and r.confidence == 0.5 and r.discovered


@pytest.mark.asyncio
async def test_enrich_with_name_only_hint_returns_none() -> None:
    handler = lambda req: httpx.Response(200, json={"items": []})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(name="Alice Doe", confidence=0.5)
    # Without a URL the SO provider has no path forward; discovery passes
    # URLs not bare names.
    assert await p.enrich(hint) is None
