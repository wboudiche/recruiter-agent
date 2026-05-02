import httpx
import pytest

from recruiter.sourcing.github import GitHubSearchClient
from recruiter.sourcing.provider import SearchError


def _client(transport: httpx.MockTransport, *, token: str | None = None) -> GitHubSearchClient:
    return GitHubSearchClient(token=token, transport=transport)


@pytest.mark.asyncio
async def test_search_users_returns_results() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/search/users"
        return httpx.Response(200, json={
            "total_count": 2,
            "items": [
                {"login": "alice", "html_url": "https://github.com/alice", "type": "User"},
                {"login": "bob", "html_url": "https://github.com/bob", "type": "User"},
            ],
        })

    c = _client(httpx.MockTransport(handler))
    results = await c.search_users("rust async", 5)
    assert len(results) == 2
    assert results[0].name == "alice"
    assert results[0].url == "https://github.com/alice"
    assert results[0].source == "github"


@pytest.mark.asyncio
async def test_search_users_sends_token_when_set() -> None:
    auth_seen: dict = {}
    def handler(req: httpx.Request) -> httpx.Response:
        auth_seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"items": []})

    c = _client(httpx.MockTransport(handler), token="ghp_abc")
    await c.search_users("x", 5)
    assert auth_seen["auth"] == "Bearer ghp_abc"


@pytest.mark.asyncio
async def test_search_users_omits_auth_header_when_no_token() -> None:
    auth_seen: dict = {}
    def handler(req: httpx.Request) -> httpx.Response:
        auth_seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"items": []})

    c = _client(httpx.MockTransport(handler), token=None)
    await c.search_users("x", 5)
    assert auth_seen["auth"] is None


@pytest.mark.asyncio
async def test_search_users_raises_transient_on_403_rate_limit() -> None:
    handler = lambda req: httpx.Response(403, json={"message": "rate limit exceeded"})
    c = _client(httpx.MockTransport(handler))
    with pytest.raises(SearchError) as ei:
        await c.search_users("x", 5)
    assert ei.value.transient is True


@pytest.mark.asyncio
async def test_search_users_raises_config_on_401() -> None:
    handler = lambda req: httpx.Response(401, text="bad token")
    c = _client(httpx.MockTransport(handler), token="ghp_bad")
    with pytest.raises(SearchError) as ei:
        await c.search_users("x", 5)
    assert ei.value.transient is False


@pytest.mark.asyncio
async def test_search_users_skips_items_without_html_url() -> None:
    handler = lambda req: httpx.Response(200, json={
        "items": [
            {"login": "alice", "html_url": "https://github.com/alice", "type": "User"},
            {"login": "broken", "type": "User"},  # missing html_url
        ],
    })
    c = _client(httpx.MockTransport(handler))
    results = await c.search_users("x", 5)
    assert len(results) == 1
    assert results[0].name == "alice"
