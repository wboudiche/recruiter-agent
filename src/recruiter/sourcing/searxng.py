import httpx

from recruiter.sourcing.provider import (
    SearchError,
    SearchResult,
    parse_linkedin_name,
    register,
)


class SearXNGProvider:
    """Self-hosted SearXNG provider. Expects the instance to have
    `formats: [json]` in its settings.yml. No auth — assumes trusted
    local-network deployment."""

    def __init__(
        self,
        *,
        base_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(transport=transport, timeout=15.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    # SearXNG returns ~10 results per page regardless of any "count" param,
    # so we paginate via `pageno` until we hit `limit`. The cap stops us
    # from looping forever if the query has a long tail of low-relevance
    # results that SearXNG keeps returning.
    _MAX_PAGES = 5

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        url = f"{self._base_url}/search"
        out: list[SearchResult] = []
        seen_urls: set[str] = set()
        for pageno in range(1, self._MAX_PAGES + 1):
            if len(out) >= limit:
                break
            params: dict[str, str | int] = {
                "q": query,
                "format": "json",
                "safesearch": 0,
                "pageno": pageno,
            }
            try:
                r = await self._client.get(url, params=params)
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                raise SearchError(
                    f"can't reach SearXNG at {self._base_url}: {e}",
                    transient=True,
                ) from e
            except httpx.HTTPError as e:
                raise SearchError(f"network failure: {e}", transient=True) from e
            if r.status_code == 429:
                raise SearchError("searxng rate limit", transient=True)
            if r.status_code >= 500:
                raise SearchError(f"searxng {r.status_code}", transient=True)
            if r.status_code != 200:
                raise SearchError(
                    f"searxng {r.status_code}: {r.text[:200]}",
                    transient=False,
                )
            try:
                payload = r.json()
            except ValueError as e:
                raise SearchError(
                    "searxng returned non-JSON; enable formats: [json] in settings.yml",
                    transient=False,
                ) from e
            items = payload.get("results") or []
            # Empty page means SearXNG has no more results — stop early
            # rather than burning more HTTP calls.
            if not items:
                break
            for it in items:
                if len(out) >= limit:
                    break
                url_value = it.get("url", "")
                # SearXNG can repeat the same URL across pages when several
                # upstream engines return it; dedupe so the user gets `limit`
                # distinct candidates, not `limit` rows that point at one.
                if not url_value or url_value in seen_urls:
                    continue
                seen_urls.add(url_value)
                title = it.get("title") or ""
                if "linkedin.com" in url_value:
                    name = parse_linkedin_name(title) or title or url_value
                else:
                    name = title or url_value
                out.append(SearchResult(
                    name=name,
                    url=url_value,
                    snippet=it.get("content", "") or "",
                    source="web",
                ))
        return out


@register("searxng")
def _factory(settings) -> SearXNGProvider:
    base = getattr(settings, "search_engine_id", None)
    if not base or not base.startswith(("http://", "https://")):
        raise SearchError(
            "searxng requires search_engine_id to be set to the instance URL "
            "(e.g. http://localhost:8080)",
            transient=False,
        )
    return SearXNGProvider(base_url=base)
