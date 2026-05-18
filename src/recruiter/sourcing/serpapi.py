import httpx

from recruiter.crypto import settings_cipher
from recruiter.sourcing.provider import (
    SearchError,
    SearchResult,
    parse_linkedin_name,
    register,
)

SERPAPI_SEARCH_URL = "https://serpapi.com/search"


class SerpAPIProvider:
    """SerpAPI Google SERP provider. Free tier of 100 searches/month, no card.
    Get a key at https://serpapi.com/."""

    def __init__(
        self,
        *,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        # SerpAPI's free tier routinely takes 10-15s to return; 10s
        # produces intermittent "network failure" toasts. 30s is generous
        # enough to cover the worst case without making the UI feel
        # unresponsive (the Search button shows "Searching…" throughout).
        self._client = httpx.AsyncClient(transport=transport, timeout=30.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        params: dict[str, str | int] = {
            "engine": "google",
            "q": query,
            "api_key": self._api_key,
            "num": min(limit, 100),  # SerpAPI caps the google engine at 100
        }
        try:
            r = await self._client.get(SERPAPI_SEARCH_URL, params=params)
        except httpx.HTTPError as e:
            raise SearchError(f"network failure: {e}", transient=True) from e
        if r.status_code in (401, 403):
            raise SearchError(f"serpapi auth: {r.text[:200]}", transient=False)
        if r.status_code == 429:
            raise SearchError("serpapi rate limit", transient=True)
        if r.status_code >= 500:
            raise SearchError(f"serpapi {r.status_code}", transient=True)
        if r.status_code != 200:
            raise SearchError(f"serpapi {r.status_code}: {r.text[:200]}", transient=False)
        payload = r.json()
        items = payload.get("organic_results") or []
        out: list[SearchResult] = []
        for it in items:
            link = it.get("link", "")
            if not link:
                continue
            name = parse_linkedin_name(it.get("title")) or it.get("title") or link
            out.append(SearchResult(
                name=name,
                url=link,
                snippet=it.get("snippet", "") or "",
                source="web",
            ))
        return out


@register("serpapi")
def _factory(settings) -> SerpAPIProvider:
    if not settings.search_api_key_enc:
        raise SearchError("serpapi requires search_api_key", transient=False)
    api_key = settings_cipher().decrypt(settings.search_api_key_enc)
    return SerpAPIProvider(api_key=api_key)
