import httpx
import pytest

from recruiter.sourcing.provider import SearchError
from recruiter.sourcing.serpapi import SerpAPIProvider


def _make_provider(transport: httpx.MockTransport) -> SerpAPIProvider:
    return SerpAPIProvider(api_key="serp_test_key", transport=transport)


@pytest.mark.asyncio
async def test_search_returns_results_for_200() -> None:
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["host"] = req.url.host
        seen["path"] = req.url.path
        seen["q"] = req.url.params.get("q")
        seen["engine"] = req.url.params.get("engine")
        seen["api_key"] = req.url.params.get("api_key")
        return httpx.Response(200, json={
            "organic_results": [
                {
                    "title": "Alice Doe - Senior Rust Engineer | LinkedIn",
                    "link": "https://www.linkedin.com/in/alice/",
                    "snippet": "5 years Rust, async / Postgres.",
                },
                {
                    "title": "Bob | LinkedIn",
                    "link": "https://www.linkedin.com/in/bob/",
                    "snippet": "Backend engineer.",
                },
            ],
        })

    p = _make_provider(httpx.MockTransport(handler))
    results = await p.search("site:linkedin.com/in/ rust engineer", 5)
    assert seen["host"] == "serpapi.com"
    assert seen["path"] == "/search"
    assert seen["engine"] == "google"
    assert seen["api_key"] == "serp_test_key"
    assert seen["q"] == "site:linkedin.com/in/ rust engineer"
    assert len(results) == 2
    assert results[0].name == "Alice Doe"
    assert results[0].url == "https://www.linkedin.com/in/alice/"
    assert "5 years Rust" in results[0].snippet
    assert results[0].source == "web"


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_results() -> None:
    handler = lambda req: httpx.Response(200, json={"organic_results": []})
    p = _make_provider(httpx.MockTransport(handler))
    assert await p.search("zzznoresults", 5) == []


@pytest.mark.asyncio
async def test_search_handles_missing_organic_results_key() -> None:
    handler = lambda req: httpx.Response(200, json={})
    p = _make_provider(httpx.MockTransport(handler))
    assert await p.search("x", 5) == []


@pytest.mark.asyncio
async def test_search_raises_config_error_on_401() -> None:
    handler = lambda req: httpx.Response(401, json={"error": "Invalid API key."})
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
        "organic_results": [{"link": "https://example.com/", "snippet": "no title"}],
    })
    p = _make_provider(httpx.MockTransport(handler))
    results = await p.search("x", 5)
    assert results[0].name == "https://example.com/"


@pytest.mark.asyncio
async def test_search_clamps_count_to_serpapi_max() -> None:
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["num"] = req.url.params.get("num")
        return httpx.Response(200, json={"organic_results": []})

    p = _make_provider(httpx.MockTransport(handler))
    await p.search("x", 999)
    assert seen["num"] == "100"


def test_serpapi_registered_in_global_registry() -> None:
    import recruiter.sourcing  # noqa: F401  triggers serpapi import
    from recruiter.sourcing.provider import resolve

    fake_settings = type("S", (), {
        "search_provider": "serpapi",
    })()
    from recruiter.crypto import settings_cipher
    enc = settings_cipher().encrypt("serp_dummy")
    fake_settings.search_api_key_enc = enc
    p = resolve(fake_settings)
    assert isinstance(p, SerpAPIProvider)


def test_serpapi_factory_raises_when_key_missing() -> None:
    import recruiter.sourcing  # noqa: F401
    from recruiter.sourcing.provider import resolve

    fake_settings = type("S", (), {
        "search_provider": "serpapi",
        "search_api_key_enc": None,
    })()
    with pytest.raises(SearchError) as ei:
        resolve(fake_settings)
    assert ei.value.transient is False
