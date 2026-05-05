import pytest
from httpx import AsyncClient

from recruiter.sourcing.provider import SearchError, SearchResult


class _FakeProvider:
    def __init__(self, *, results=None, raises=None) -> None:
        self._results = results or []
        self._raises = raises

    async def search(self, query, limit):
        if self._raises:
            raise self._raises
        return self._results


async def _seed_settings(api_client: AsyncClient) -> None:
    """Settings row must exist with search_provider=google_cse so the
    provider resolver returns non-None when monkeypatched."""
    await api_client.put("/api/settings", json={
        "search_provider": "google_cse",
        "search_api_key": "x",
        "search_engine_id": "cx",
    })


@pytest.mark.asyncio
async def test_multi_source_happy_path(api_client: AsyncClient, monkeypatch) -> None:
    await _seed_settings(api_client)
    fake = _FakeProvider(results=[
        SearchResult(name="Alice", url="https://www.linkedin.com/in/alice/",
                     snippet="bio", source="web"),
    ])
    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _s: fake)

    class _FakeGH:
        def __init__(self, *, token, transport=None): pass
        async def search_users(self, q, limit):
            return [SearchResult(name="bob", url="https://github.com/bob",
                                 snippet="x", source="github")]
        async def aclose(self): pass

    import recruiter.sourcing.search as search_mod
    monkeypatch.setattr(search_mod, "GitHubSearchClient", _FakeGH)

    r = await api_client.post("/api/sourcing/search", json={
        "sources": ["linkedin", "github"],
        "query": "rust",
        "limit_per_source": 5,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["errors"] == []
    sources_in_results = {x["source"] for x in body["results"]}
    assert sources_in_results == {"linkedin", "github"}
    li = next(x for x in body["results"] if x["source"] == "linkedin")
    assert li["name"] == "Alice"


@pytest.mark.asyncio
async def test_partial_failure_returns_both_results_and_errors(
    api_client: AsyncClient, monkeypatch,
) -> None:
    await _seed_settings(api_client)
    fake_provider = _FakeProvider(raises=SearchError("config", transient=False))
    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _s: fake_provider)

    class _FakeGH:
        def __init__(self, *, token, transport=None): pass
        async def search_users(self, q, limit):
            return [SearchResult(name="bob", url="https://github.com/bob",
                                 snippet="x", source="github")]
        async def aclose(self): pass

    import recruiter.sourcing.search as search_mod
    monkeypatch.setattr(search_mod, "GitHubSearchClient", _FakeGH)

    r = await api_client.post("/api/sourcing/search", json={
        "sources": ["linkedin", "github"],
        "query": "rust",
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["source"] == "github"
    assert len(body["errors"]) == 1
    assert body["errors"][0]["source"] == "linkedin"
    assert body["errors"][0]["transient"] is False
    assert "config" in body["errors"][0]["reason"]


@pytest.mark.asyncio
async def test_all_errored(api_client: AsyncClient, monkeypatch) -> None:
    await _seed_settings(api_client)
    fake_provider = _FakeProvider(raises=SearchError("rate", transient=True))
    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _s: fake_provider)

    class _BrokenGH:
        def __init__(self, *, token, transport=None): pass
        async def search_users(self, q, limit):
            raise SearchError("github 5xx", transient=True)
        async def aclose(self): pass

    import recruiter.sourcing.search as search_mod
    monkeypatch.setattr(search_mod, "GitHubSearchClient", _BrokenGH)

    r = await api_client.post("/api/sourcing/search", json={
        "sources": ["linkedin", "web", "github"],
        "query": "rust",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["results"] == []
    assert {e["source"] for e in body["errors"]} == {"linkedin", "web", "github"}
    assert all(e["transient"] for e in body["errors"])


@pytest.mark.asyncio
async def test_422_empty_sources(api_client: AsyncClient) -> None:
    r = await api_client.post("/api/sourcing/search", json={
        "sources": [], "query": "rust",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_422_empty_query(api_client: AsyncClient) -> None:
    r = await api_client.post("/api/sourcing/search", json={
        "sources": ["github"], "query": "",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_422_limit_out_of_range(api_client: AsyncClient) -> None:
    r = await api_client.post("/api/sourcing/search", json={
        "sources": ["github"], "query": "rust", "limit_per_source": 100,
    })
    assert r.status_code == 422
