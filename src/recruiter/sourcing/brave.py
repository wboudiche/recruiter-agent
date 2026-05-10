import httpx

from recruiter.crypto import settings_cipher
from recruiter.sourcing.provider import (
    SearchError,
    SearchResult,
    parse_linkedin_name,
    register,
)

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveSearchProvider:
    """Brave Search API provider. Free tier of 2000 queries/month, no card.
    Get a key at https://brave.com/search/api/."""

    def __init__(
        self,
        *,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        params: dict[str, str | int] = {
            "q": query,
            "count": max(1, min(limit, 20)),  # Brave caps at 20 per call
        }
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self._api_key,
        }
        try:
            r = await self._client.get(BRAVE_SEARCH_URL, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise SearchError(f"network failure: {e}", transient=True) from e
        if r.status_code in (401, 403):
            raise SearchError(f"brave auth: {r.text[:200]}", transient=False)
        if r.status_code == 429:
            raise SearchError("brave rate limit", transient=True)
        if r.status_code >= 500:
            raise SearchError(f"brave {r.status_code}", transient=True)
        if r.status_code != 200:
            raise SearchError(f"brave {r.status_code}: {r.text[:200]}", transient=False)
        web = r.json().get("web") or {}
        items = web.get("results") or []
        out: list[SearchResult] = []
        for it in items:
            url = it.get("url", "")
            if not url:
                continue
            name = parse_linkedin_name(it.get("title")) or it.get("title") or url
            out.append(SearchResult(
                name=name,
                url=url,
                snippet=it.get("description", "") or "",
                source="web",
            ))
        return out


@register("brave")
def _factory(settings) -> BraveSearchProvider:
    if not settings.search_api_key_enc:
        raise SearchError("brave requires search_api_key", transient=False)
    api_key = settings_cipher().decrypt(settings.search_api_key_enc)
    return BraveSearchProvider(api_key=api_key)
