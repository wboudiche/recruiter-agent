from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import ClassVar

import httpx

from recruiter.enrichment.provider import (
    EnrichmentHint,
    EnrichmentResult,
    EnrichmentSignal,
    register,
)

logger = logging.getLogger(__name__)

UA = "recruiter-agent/0.1 (+https://example.invalid)"


def _username_from_reddit_url(url: str) -> str | None:
    m = re.search(r"reddit\.com/u(?:ser)?/([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else None


@register("reddit")
class RedditProvider:
    name: ClassVar[str] = "reddit"
    domains: ClassVar[list[str]] = ["reddit.com", "old.reddit.com", "www.reddit.com"]

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            transport=transport, timeout=10.0, headers={"User-Agent": UA}
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        username = _username_from_reddit_url(hint.url) if hint.url else None
        if not username:
            return None

        profile_url = f"https://www.reddit.com/user/{username}"
        about_url = f"https://www.reddit.com/user/{username}/about.json"
        comments_url = f"https://www.reddit.com/user/{username}/comments.json?limit=10"

        try:
            about = await self._client.get(about_url)
            comments = await self._client.get(comments_url)
        except httpx.HTTPError as exc:
            logger.info("reddit fetch failed for %s: %s", username, exc)
            return None
        for r in (about, comments):
            if r.status_code != 200:
                logger.info("reddit returned %s for %s", r.status_code, username)
                return None
        try:
            about_data = about.json().get("data", {}) or {}
            children = comments.json().get("data", {}).get("children", []) or []
        except ValueError:
            return None

        signals: list[EnrichmentSignal] = []
        bio = (about_data.get("subreddit") or {}).get("public_description")
        link_k = about_data.get("link_karma")
        cmt_k = about_data.get("comment_karma")
        if link_k is not None or cmt_k is not None:
            signals.append(EnrichmentSignal(
                type="profile",
                summary=f"Reddit profile: {link_k or 0} link karma, {cmt_k or 0} comment karma"
                        + (f". Bio: {bio}" if bio else ""),
                url=profile_url,
            ))
        for c in children[:4]:
            d = c.get("data") or {}
            body = (d.get("body") or "")[:140]
            sub = d.get("subreddit") or "unknown"
            permalink = d.get("permalink")
            url = f"https://www.reddit.com{permalink}" if permalink else None
            ts = d.get("created_utc")
            ts_parsed = (
                datetime.fromtimestamp(ts, tz=timezone.utc)
                if isinstance(ts, (int, float))
                else None
            )
            signals.append(EnrichmentSignal(
                type="post",
                summary=f"r/{sub}: {body}",
                url=url,
                timestamp=ts_parsed,
            ))
        if not signals:
            return None

        summary = f"Reddit user u/{username}; {len(children)} recent comments."
        return EnrichmentResult(
            source="reddit",
            profile_url=profile_url,
            confidence=hint.confidence,
            discovered=hint.confidence < 1.0,
            signals=signals[:5],
            summary=summary,
        )
