import httpx
import pytest

from recruiter.enrichment.github import GitHubEnrichmentProvider
from recruiter.enrichment.provider import EnrichmentHint


def _make_provider(transport: httpx.MockTransport, **kw) -> GitHubEnrichmentProvider:
    return GitHubEnrichmentProvider(transport=transport, **kw)


def _user_resp() -> dict:
    return {
        "login": "alice",
        "name": "Alice Doe",
        "bio": "Rust + async",
        "public_repos": 42,
        "followers": 200,
        "html_url": "https://github.com/alice",
        "blog": "https://alice.dev",
        "company": "Acme",
        "email": "alice@acme.com",
    }


def _repos_resp() -> list[dict]:
    return [
        {"name": "rust-helper", "html_url": "https://github.com/alice/rust-helper",
         "stargazers_count": 120, "language": "Rust",
         "description": "async helpers", "pushed_at": "2025-04-01T12:00:00Z"},
        {"name": "pg-tools", "html_url": "https://github.com/alice/pg-tools",
         "stargazers_count": 30, "language": "Python",
         "description": "Postgres tools", "pushed_at": "2025-03-01T12:00:00Z"},
    ]


@pytest.mark.asyncio
async def test_enrich_known_user_returns_signals() -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        if req.url.path == "/users/alice":
            return httpx.Response(200, json=_user_resp())
        if req.url.path == "/users/alice/repos":
            return httpx.Response(200, json=_repos_resp())
        return httpx.Response(404)

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://github.com/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert r.source == "github"
    assert r.profile_url == "https://github.com/alice"
    assert r.confidence == 1.0
    assert any("rust-helper" in s.summary for s in r.signals)


@pytest.mark.asyncio
async def test_enrich_passes_bearer_token_when_provided() -> None:
    seen_auth: list[str | None] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_auth.append(req.headers.get("Authorization"))
        if req.url.path == "/users/alice":
            return httpx.Response(200, json=_user_resp())
        return httpx.Response(200, json=[])

    p = _make_provider(httpx.MockTransport(handler), token="ghp_xxx")
    hint = EnrichmentHint(url="https://github.com/alice", confidence=1.0)
    await p.enrich(hint)
    assert all(a == "Bearer ghp_xxx" for a in seen_auth if a)


@pytest.mark.asyncio
async def test_enrich_returns_none_on_404() -> None:
    handler = lambda req: httpx.Response(404, json={"message": "Not Found"})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://github.com/ghost", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_401() -> None:
    handler = lambda req: httpx.Response(401, json={"message": "Bad credentials"})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://github.com/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_403_rate_limit() -> None:
    handler = lambda req: httpx.Response(403, json={"message": "rate limit"})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://github.com/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_5xx() -> None:
    handler = lambda req: httpx.Response(503)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://github.com/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_network_failure() -> None:
    def handler(req): raise httpx.ConnectError("refused", request=req)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://github.com/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_caps_signals_at_5() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/users/alice":
            return httpx.Response(200, json=_user_resp())
        return httpx.Response(200, json=[
            {"name": f"r{i}", "html_url": f"https://github.com/alice/r{i}",
             "stargazers_count": i, "language": "Python", "description": "x",
             "pushed_at": "2025-01-01T00:00:00Z"}
            for i in range(20)
        ])
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://github.com/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None and len(r.signals) <= 5


@pytest.mark.asyncio
async def test_enrich_emits_email_signal_when_user_has_public_email() -> None:
    """The user's public email should appear in a signal so the identity
    engine can match it against the candidate's anchor email."""
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/users/alice":
            return httpx.Response(200, json=_user_resp())
        return httpx.Response(200, json=[])
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://github.com/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert any("alice@acme.com" in s.summary for s in r.signals)


@pytest.mark.asyncio
async def test_enrich_propagates_low_confidence() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/users/alice":
            return httpx.Response(200, json=_user_resp())
        return httpx.Response(200, json=_repos_resp())
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://github.com/alice", confidence=0.5)
    r = await p.enrich(hint)
    assert r is not None and r.confidence == 0.5 and r.discovered
