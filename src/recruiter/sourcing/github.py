import httpx

from recruiter.sourcing.provider import SearchError, SearchResult


GITHUB_SEARCH_URL = "https://api.github.com/search/users"


class GitHubSearchClient:
    """Direct REST client for GitHub's /search/users endpoint.

    Standalone — does not implement SearchProvider Protocol because GitHub
    doesn't fit the same query-shape model (no `site:` operator equivalent).
    Token is optional; presence raises rate limit from 60/hr to 5000/hr.
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = token
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search_users(self, query: str, limit: int) -> list[SearchResult]:
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        params: dict[str, str | int] = {"q": query, "per_page": max(1, min(limit, 30))}
        try:
            r = await self._client.get(GITHUB_SEARCH_URL, headers=headers, params=params)
        except httpx.HTTPError as e:
            raise SearchError(f"network failure: {e}", transient=True) from e
        if r.status_code == 401:
            raise SearchError(f"github auth: {r.text[:200]}", transient=False)
        if r.status_code == 403:
            # GitHub returns 403 for rate-limit and abuse detection — both transient.
            raise SearchError(f"github rate-limit/forbidden: {r.text[:200]}", transient=True)
        if r.status_code >= 500:
            raise SearchError(f"github {r.status_code}", transient=True)
        if r.status_code != 200:
            raise SearchError(f"github {r.status_code}: {r.text[:200]}", transient=False)
        items = r.json().get("items", []) or []
        return [
            SearchResult(
                name=it.get("login", ""),
                url=it.get("html_url", ""),
                snippet=f"GitHub user — {it.get('type', 'User')}",
                source="github",
            )
            for it in items
            if it.get("html_url")
        ]
