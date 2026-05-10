from __future__ import annotations

import logging
from datetime import datetime
from typing import ClassVar
from urllib.parse import parse_qs, urlparse

import httpx

from recruiter.enrichment.provider import (
    EnrichmentHint,
    EnrichmentResult,
    EnrichmentSignal,
    register,
)

logger = logging.getLogger(__name__)

HN_SEARCH = "https://hn.algolia.com/api/v1/search"


def _username_from_hn_url(url: str) -> str | None:
    parsed = urlparse(url)
    if "news.ycombinator.com" not in (parsed.hostname or ""):
        return None
    qs = parse_qs(parsed.query)
    if "id" in qs:
        return qs["id"][0]
    return None


@register("hackernews")
class HackerNewsProvider:
    name: ClassVar[str] = "hackernews"
    domains: ClassVar[list[str]] = ["news.ycombinator.com"]

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        username: str | None = None
        if hint.url:
            username = _username_from_hn_url(hint.url)
        if not username:
            return None
        profile_url = f"https://news.ycombinator.com/user?id={username}"

        try:
            r = await self._client.get(
                HN_SEARCH,
                params={"tags": f"story,author_{username}", "hitsPerPage": 5},
            )
        except httpx.HTTPError as exc:
            logger.info("hackernews fetch failed for %s: %s", username, exc)
            return None
        if r.status_code != 200:
            logger.info("hackernews returned %s for %s", r.status_code, username)
            return None

        try:
            payload = r.json()
        except ValueError:
            return None

        hits = payload.get("hits") or []
        signals: list[EnrichmentSignal] = []
        for h in hits[:5]:
            title = h.get("title")
            url = h.get("url") or (
                f"https://news.ycombinator.com/item?id={h['objectID']}"
                if h.get("objectID") else None
            )
            ts = h.get("created_at")
            if not title:
                continue
            try:
                ts_parsed = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
            except (ValueError, AttributeError):
                ts_parsed = None
            signals.append(EnrichmentSignal(
                type="post",
                summary=f'HN story: "{title}" ({h.get("points", 0)} points)',
                url=url,
                timestamp=ts_parsed,
            ))

        if not signals:
            return None

        summary = (
            f"Active on Hacker News as {username}: {len(hits)} stories. "
            f"Top: {signals[0].summary[:120]}"
        )
        return EnrichmentResult(
            source="hackernews",
            profile_url=profile_url,
            confidence=hint.confidence,
            discovered=hint.confidence < 1.0,
            signals=signals,
            summary=summary,
        )
