import pytest

from recruiter.sourcing.provider import SearchError, SearchResult
from recruiter.sourcing.search import search_one_source


class _FakeProvider:
    def __init__(self, results=None, raises=None) -> None:
        self._results = results or []
        self._raises = raises
        self.last_query: str | None = None

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        self.last_query = query
        if self._raises:
            raise self._raises
        return self._results


@pytest.fixture
def fake_settings():
    return type("S", (), {
        "search_provider": "google_cse",
        "search_api_key_enc": b"x",
        "search_engine_id": "cx",
        "github_token_enc": None,
    })()


@pytest.mark.asyncio
async def test_search_linkedin_prepends_site_operator(fake_settings, monkeypatch) -> None:
    fake = _FakeProvider(results=[
        SearchResult(name="Alice", url="https://www.linkedin.com/in/alice/",
                     snippet="bio", source="web"),
    ])
    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _s: fake)

    out = await search_one_source(
        "linkedin", "rust postgres", 5, settings=fake_settings,
    )
    assert fake.last_query == "site:linkedin.com/in/ rust postgres"
    assert out[0].source == "linkedin"  # overridden from "web"


@pytest.mark.asyncio
async def test_search_web_passes_query_verbatim(fake_settings, monkeypatch) -> None:
    fake = _FakeProvider(results=[
        SearchResult(name="x", url="https://x", snippet="y", source="web"),
    ])
    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _s: fake)

    out = await search_one_source(
        "web", "remote python staff engineer", 5, settings=fake_settings,
    )
    assert fake.last_query == "remote python staff engineer"
    assert out[0].source == "web"


@pytest.mark.asyncio
async def test_search_github_uses_client_not_registry(
    fake_settings, monkeypatch,
) -> None:
    captured: dict = {}

    class _FakeGH:
        def __init__(self, *, token, transport=None) -> None:
            captured["token"] = token

        async def search_users(self, q, limit):
            return [SearchResult(name="alice", url="https://github.com/alice",
                                 snippet="x", source="github")]

        async def aclose(self): pass

    import recruiter.sourcing.search as search_mod
    monkeypatch.setattr(search_mod, "GitHubSearchClient", _FakeGH)

    out = await search_one_source(
        "github", "rust", 5, settings=fake_settings,  # github_token_enc=None
    )
    assert captured["token"] is None
    assert out[0].source == "github"


@pytest.mark.asyncio
async def test_search_raises_when_settings_unset() -> None:
    with pytest.raises(SearchError) as ei:
        await search_one_source("linkedin", "x", 5, settings=None)
    assert ei.value.transient is False


@pytest.mark.asyncio
async def test_search_raises_when_provider_unconfigured(
    fake_settings, monkeypatch,
) -> None:
    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _s: None)
    with pytest.raises(SearchError) as ei:
        await search_one_source("linkedin", "x", 5, settings=fake_settings)
    assert ei.value.transient is False


@pytest.mark.asyncio
async def test_search_propagates_provider_error(
    fake_settings, monkeypatch,
) -> None:
    fake = _FakeProvider(raises=SearchError("rate limit", transient=True))
    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _s: fake)
    with pytest.raises(SearchError) as ei:
        await search_one_source("web", "x", 5, settings=fake_settings)
    assert ei.value.transient is True
