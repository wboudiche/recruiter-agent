import httpx
import pytest

from recruiter.pipeline.fetchers.github import fetch_github


@pytest.mark.asyncio
async def test_fetch_github_combines_user_and_repos() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/users/alice":
            return httpx.Response(
                200,
                json={
                    "login": "alice",
                    "name": "Alice Doe",
                    "bio": "Backend engineer",
                    "location": "Paris",
                    "blog": "https://alice.dev",
                    "email": "alice@example.com",
                    "company": "Acme",
                },
            )
        if request.url.path == "/users/alice/repos":
            return httpx.Response(
                200,
                json=[
                    {"name": "serverpaint", "description": "Distributed paint", "language": "Rust", "stargazers_count": 12, "fork": False},
                    {"name": "fork-thing", "description": "irrelevant", "language": "Go", "stargazers_count": 0, "fork": True},
                ],
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    result = await fetch_github("https://github.com/alice", transport=transport)

    assert "Alice Doe" in result.text
    assert "Backend engineer" in result.text
    assert "serverpaint" in result.text
    assert "fork-thing" not in result.text
    assert result.metadata["login"] == "alice"


@pytest.mark.asyncio
async def test_fetch_github_rejects_non_github_urls() -> None:
    with pytest.raises(ValueError, match="not a github profile URL"):
        await fetch_github("https://example.com/foo")
