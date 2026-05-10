import httpx
import pytest

from recruiter.sourcing.brave import BraveSearchProvider
from recruiter.sourcing.provider import SearchError


def _make_provider(transport: httpx.MockTransport) -> BraveSearchProvider:
    return BraveSearchProvider(api_key="brv_test_key", transport=transport)


@pytest.mark.asyncio
async def test_search_returns_results_for_200() -> None:
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["host"] = req.url.host
        seen["path"] = req.url.path
        seen["token_header"] = req.headers.get("x-subscription-token")
        seen["accept"] = req.headers.get("accept")
        seen["q"] = req.url.params.get("q")
        return httpx.Response(200, json={
            "web": {
                "results": [
                    {
                        "title": "Alice Doe - Senior Rust Engineer | LinkedIn",
                        "url": "https://www.linkedin.com/in/alice/",
                        "description": "5 years Rust, async / Postgres.",
                    },
                    {
                        "title": "Bob | LinkedIn",
                        "url": "https://www.linkedin.com/in/bob/",
                        "description": "Backend engineer.",
                    },
                ],
            },
        })

    p = _make_provider(httpx.MockTransport(handler))
    results = await p.search("site:linkedin.com/in/ rust engineer", 5)
    assert seen["host"] == "api.search.brave.com"
    assert seen["path"] == "/res/v1/web/search"
    assert seen["token_header"] == "brv_test_key"
    assert seen["accept"] == "application/json"
    assert seen["q"] == "site:linkedin.com/in/ rust engineer"
    assert len(results) == 2
    assert results[0].name == "Alice Doe"
    assert results[0].url == "https://www.linkedin.com/in/alice/"
    assert "5 years Rust" in results[0].snippet
    assert results[0].source == "web"


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_results() -> None:
    handler = lambda req: httpx.Response(200, json={"web": {"results": []}})
    p = _make_provider(httpx.MockTransport(handler))
    assert await p.search("zzznoresults", 5) == []


@pytest.mark.asyncio
async def test_search_handles_missing_web_key() -> None:
    handler = lambda req: httpx.Response(200, json={})
    p = _make_provider(httpx.MockTransport(handler))
    assert await p.search("x", 5) == []


@pytest.mark.asyncio
async def test_search_raises_config_error_on_401() -> None:
    handler = lambda req: httpx.Response(401, text="bad key")
    p = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(SearchError) as ei:
        await p.search("x", 5)
    assert ei.value.transient is False


@pytest.mark.asyncio
async def test_search_raises_transient_error_on_429() -> None:
    handler = lambda req: httpx.Response(429, text="rate")
    p = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(SearchError) as ei:
        await p.search("x", 5)
    assert ei.value.transient is True


@pytest.mark.asyncio
async def test_search_raises_transient_error_on_5xx() -> None:
    handler = lambda req: httpx.Response(503, text="oops")
    p = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(SearchError) as ei:
        await p.search("x", 5)
    assert ei.value.transient is True


@pytest.mark.asyncio
async def test_search_falls_back_to_url_when_title_missing() -> None:
    handler = lambda req: httpx.Response(200, json={
        "web": {"results": [{"url": "https://example.com/", "description": "no title"}]},
    })
    p = _make_provider(httpx.MockTransport(handler))
    results = await p.search("x", 5)
    assert results[0].name == "https://example.com/"


@pytest.mark.asyncio
async def test_search_clamps_count_to_brave_max() -> None:
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["count"] = req.url.params.get("count")
        return httpx.Response(200, json={"web": {"results": []}})

    p = _make_provider(httpx.MockTransport(handler))
    await p.search("x", 999)
    assert seen["count"] == "20"
