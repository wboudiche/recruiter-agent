import httpx
import pytest

from recruiter.sourcing.provider import SearchError
from recruiter.sourcing.searxng import SearXNGProvider


def _make_provider(transport: httpx.MockTransport) -> SearXNGProvider:
    return SearXNGProvider(base_url="http://localhost:8080", transport=transport)


@pytest.mark.asyncio
async def test_search_hits_search_endpoint_with_json_format() -> None:
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["host"] = req.url.host
        seen["path"] = req.url.path
        seen["q"] = req.url.params.get("q")
        seen["format"] = req.url.params.get("format")
        return httpx.Response(200, json={"results": []})

    p = _make_provider(httpx.MockTransport(handler))
    await p.search("rust engineer", 5)
    assert seen["host"] == "localhost"
    assert seen["path"] == "/search"
    assert seen["q"] == "rust engineer"
    assert seen["format"] == "json"


@pytest.mark.asyncio
async def test_search_maps_results_and_parses_linkedin_titles() -> None:
    handler = lambda req: httpx.Response(200, json={
        "results": [
            {
                "title": "Alice Doe - Senior Rust | LinkedIn",
                "url": "https://www.linkedin.com/in/alice/",
                "content": "Async Rust + Postgres",
            },
            {
                "title": "Acme — Hiring Rust Engineers",
                "url": "https://acme.example/jobs",
                "content": "We hire Rust engineers",
            },
        ],
    })
    p = _make_provider(httpx.MockTransport(handler))
    results = await p.search("rust", 5)
    assert len(results) == 2
    # LinkedIn URL: name parsed from title.
    assert results[0].name == "Alice Doe"
    assert results[0].url == "https://www.linkedin.com/in/alice/"
    # Non-LinkedIn URL: title kept as-is.
    assert results[1].name == "Acme — Hiring Rust Engineers"
    assert results[1].source == "web"


@pytest.mark.asyncio
async def test_search_clamps_to_limit() -> None:
    handler = lambda req: httpx.Response(200, json={
        "results": [
            {"title": f"r{i}", "url": f"https://x/{i}", "content": ""}
            for i in range(10)
        ],
    })
    p = _make_provider(httpx.MockTransport(handler))
    results = await p.search("x", 3)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_search_raises_transient_on_connect_failure() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=req)

    p = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(SearchError) as ei:
        await p.search("x", 5)
    assert ei.value.transient is True
    assert "localhost:8080" in str(ei.value)


@pytest.mark.asyncio
async def test_search_raises_config_error_on_non_200() -> None:
    handler = lambda req: httpx.Response(403, text="forbidden")
    p = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(SearchError) as ei:
        await p.search("x", 5)
    assert ei.value.transient is False


@pytest.mark.asyncio
async def test_search_raises_when_response_is_not_json() -> None:
    handler = lambda req: httpx.Response(
        200, text="<!DOCTYPE html><html>...</html>",
        headers={"content-type": "text/html"},
    )
    p = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(SearchError) as ei:
        await p.search("x", 5)
    assert ei.value.transient is False
    assert "json" in str(ei.value).lower()


def test_factory_raises_when_url_missing() -> None:
    import recruiter.sourcing  # noqa: F401
    from recruiter.sourcing.provider import resolve

    fake_settings = type("S", (), {
        "search_provider": "searxng",
        "search_engine_id": None,
    })()
    with pytest.raises(SearchError) as ei:
        resolve(fake_settings)
    assert ei.value.transient is False


def test_factory_raises_when_url_not_http() -> None:
    import recruiter.sourcing  # noqa: F401
    from recruiter.sourcing.provider import resolve

    fake_settings = type("S", (), {
        "search_provider": "searxng",
        "search_engine_id": "localhost:8080",  # missing scheme
    })()
    with pytest.raises(SearchError) as ei:
        resolve(fake_settings)
    assert ei.value.transient is False


def test_factory_strips_trailing_slash() -> None:
    import recruiter.sourcing  # noqa: F401
    from recruiter.sourcing.provider import resolve

    fake_settings = type("S", (), {
        "search_provider": "searxng",
        "search_engine_id": "http://localhost:8080/",
    })()
    p = resolve(fake_settings)
    assert isinstance(p, SearXNGProvider)
    assert p._base_url == "http://localhost:8080"
