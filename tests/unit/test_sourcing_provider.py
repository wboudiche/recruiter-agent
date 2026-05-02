import pytest

from recruiter.sourcing.provider import (
    SearchError,
    SearchProvider,
    SearchResult,
    register,
    resolve,
)


class _Stub(SearchProvider):
    async def search(self, query: str, limit: int) -> list[SearchResult]:
        return [SearchResult(name="x", url="https://x", snippet="y", source="web")]


def test_search_result_holds_required_fields() -> None:
    r = SearchResult(name="Alice", url="https://x", snippet="bio", source="linkedin")
    assert r.name == "Alice"
    assert r.source == "linkedin"


def test_search_error_carries_transient_flag() -> None:
    e = SearchError("rate limit", transient=True)
    assert e.transient is True
    assert "rate limit" in str(e)


def test_registry_resolves_registered_provider() -> None:
    @register("stub")
    def _factory(_settings):
        return _Stub()

    fake_settings = type("S", (), {
        "search_provider": "stub",
        "search_api_key_enc": b"x",
        "search_engine_id": "y",
    })()
    p = resolve(fake_settings)
    assert isinstance(p, _Stub)


def test_registry_returns_none_when_unconfigured() -> None:
    fake_settings = type("S", (), {"search_provider": None})()
    assert resolve(fake_settings) is None


def test_registry_returns_none_for_unknown_provider() -> None:
    fake_settings = type("S", (), {"search_provider": "nonexistent_xyz"})()
    assert resolve(fake_settings) is None
