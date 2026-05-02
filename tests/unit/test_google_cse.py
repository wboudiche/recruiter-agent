import httpx
import pytest

from recruiter.sourcing.google_cse import GoogleCSEProvider
from recruiter.sourcing.provider import SearchError


def _make_provider(transport: httpx.MockTransport) -> GoogleCSEProvider:
    return GoogleCSEProvider(api_key="k", cse_id="cx", transport=transport)


@pytest.mark.asyncio
async def test_search_returns_results_for_200() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/customsearch/v1")
        return httpx.Response(200, json={
            "items": [
                {"title": "Alice Doe - Senior Rust Engineer | LinkedIn",
                 "link": "https://www.linkedin.com/in/alice/",
                 "snippet": "5 years Rust, async / Postgres."},
                {"title": "Bob | LinkedIn",
                 "link": "https://www.linkedin.com/in/bob/",
                 "snippet": "Backend engineer."},
            ],
        })
    p = _make_provider(httpx.MockTransport(handler))
    results = await p.search("site:linkedin.com/in/ rust engineer", 5)
    assert len(results) == 2
    assert results[0].name == "Alice Doe"  # parsed before the first " - "
    assert results[0].url == "https://www.linkedin.com/in/alice/"
    assert "5 years Rust" in results[0].snippet
    # Provider always sets source="web"; the chat-tool wrapper overrides per source.
    assert results[0].source == "web"


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_items() -> None:
    handler = lambda req: httpx.Response(200, json={"queries": {}})
    p = _make_provider(httpx.MockTransport(handler))
    assert await p.search("zzznoresultsxxx", 5) == []


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
async def test_search_falls_back_to_link_when_title_missing() -> None:
    handler = lambda req: httpx.Response(200, json={
        "items": [{"link": "https://example.com/", "snippet": "no title"}],
    })
    p = _make_provider(httpx.MockTransport(handler))
    results = await p.search("x", 5)
    assert results[0].name == "https://example.com/"
