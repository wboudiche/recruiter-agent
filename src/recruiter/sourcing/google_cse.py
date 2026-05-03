import httpx

from recruiter.crypto import settings_cipher
from recruiter.sourcing.provider import SearchError, SearchResult, register


GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"


def _parse_name(title: str | None) -> str | None:
    """LinkedIn titles look like 'Alice Doe - Senior Rust | LinkedIn'.
    Strip the '| LinkedIn' suffix and take the first ' - ' segment.
    Returns None if the title is empty / missing."""
    if not title:
        return None
    cleaned = title.split(" | ")[0].strip()
    return cleaned.split(" - ")[0].strip() or None


class GoogleCSEProvider:
    """Google Custom Search Engine provider. Configure a CSE in cse.google.com,
    enable the Custom Search API in Google Cloud Console, and pass the API
    key + CX here."""

    def __init__(
        self,
        *,
        api_key: str,
        cse_id: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._cse_id = cse_id
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        params: dict[str, str | int] = {
            "key": self._api_key,
            "cx": self._cse_id,
            "q": query,
            "num": max(1, min(limit, 10)),  # CSE caps at 10 per call
        }
        try:
            r = await self._client.get(GOOGLE_CSE_URL, params=params)
        except httpx.HTTPError as e:
            raise SearchError(f"network failure: {e}", transient=True) from e
        if r.status_code in (401, 403):
            raise SearchError(f"google CSE auth: {r.text[:200]}", transient=False)
        if r.status_code == 429:
            raise SearchError("google CSE rate limit", transient=True)
        if r.status_code >= 500:
            raise SearchError(f"google CSE {r.status_code}", transient=True)
        if r.status_code != 200:
            raise SearchError(f"google CSE {r.status_code}: {r.text[:200]}", transient=False)
        items = r.json().get("items", []) or []
        out: list[SearchResult] = []
        for it in items:
            link = it.get("link", "")
            if not link:
                continue
            name = _parse_name(it.get("title")) or link
            out.append(SearchResult(
                name=name,
                url=link,
                snippet=it.get("snippet", "") or "",
                source="web",
            ))
        return out


@register("google_cse")
def _factory(settings) -> GoogleCSEProvider:
    if not settings.search_api_key_enc or not settings.search_engine_id:
        raise SearchError(
            "google_cse requires both search_api_key and search_engine_id",
            transient=False,
        )
    api_key = settings_cipher().decrypt(settings.search_api_key_enc)
    return GoogleCSEProvider(api_key=api_key, cse_id=settings.search_engine_id)
