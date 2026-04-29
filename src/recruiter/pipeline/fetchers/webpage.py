import httpx
import trafilatura

from recruiter.pipeline.parsers.text import ParsedContent


async def fetch_webpage(
    url: str,
    *,
    transport: httpx.AsyncBaseTransport | httpx.MockTransport | None = None,
) -> ParsedContent:
    async with httpx.AsyncClient(
        transport=transport,
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": "recruiter-agent/0.1"},
    ) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ValueError(f"fetch failed: {exc}") from exc

    html = response.text
    extracted = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    return ParsedContent(text=extracted.strip(), metadata={"source_url": url, "status_code": response.status_code})
