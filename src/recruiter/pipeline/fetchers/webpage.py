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
        except httpx.HTTPStatusError as exc:
            # Many job boards / aggregator sites return 403/429 to anything
            # without a real browser fingerprint. Surface a message the user
            # can act on rather than dumping the raw httpx error.
            raise ValueError(
                f"This page couldn't be fetched (HTTP {exc.response.status_code}). "
                "The site likely blocks automated access — try the Paste tab "
                "to add the candidate manually."
            ) from exc
        except httpx.RequestError as exc:
            raise ValueError(
                "This page couldn't be reached (network error). "
                "Try the Paste tab to add the candidate manually."
            ) from exc

    html = response.text
    extracted = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    return ParsedContent(text=extracted.strip(), metadata={"source_url": url, "status_code": response.status_code})
