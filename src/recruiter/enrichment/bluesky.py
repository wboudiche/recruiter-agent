from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import ClassVar

import httpx

from recruiter.enrichment.provider import (
    EnrichmentHint,
    EnrichmentResult,
    EnrichmentSignal,
    register,
)

logger = logging.getLogger(__name__)

BSKY_BASE = "https://public.api.bsky.app/xrpc"


def _handle_from_url(url: str) -> str | None:
    m = re.search(r"bsky\.app/profile/([A-Za-z0-9._:-]+)", url or "")
    return m.group(1) if m else None


@register("bluesky")
class BlueskyProvider:
    name: ClassVar[str] = "bluesky"
    domains: ClassVar[list[str]] = ["bsky.app"]

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        handle = _handle_from_url(hint.url) if hint.url else None
        if not handle:
            return None
        try:
            prof = await self._client.get(
                f"{BSKY_BASE}/app.bsky.actor.getProfile", params={"actor": handle}
            )
        except httpx.HTTPError as exc:
            logger.info("bluesky getProfile failed for %s: %s", handle, exc)
            return None
        if prof.status_code != 200:
            logger.info("bluesky getProfile %s for %s", prof.status_code, handle)
            return None
        try:
            profile = prof.json()
        except ValueError:
            return None

        try:
            feed_resp = await self._client.get(
                f"{BSKY_BASE}/app.bsky.feed.getAuthorFeed",
                params={"actor": handle, "limit": 5},
            )
        except httpx.HTTPError as exc:
            logger.info("bluesky getAuthorFeed failed for %s: %s", handle, exc)
            return None
        if feed_resp.status_code != 200:
            return None
        try:
            feed = feed_resp.json().get("feed") or []
        except ValueError:
            return None

        signals: list[EnrichmentSignal] = []
        desc = profile.get("description")
        if desc:
            signals.append(EnrichmentSignal(
                type="profile",
                summary=f"Bluesky bio: {desc[:200]}",
                url=f"https://bsky.app/profile/{handle}",
            ))
        for item in feed[:4]:
            post = item.get("post") or {}
            rec = post.get("record") or {}
            text = (rec.get("text") or "")[:160]
            uri = post.get("uri") or ""
            ts = rec.get("createdAt") or post.get("indexedAt")
            try:
                ts_parsed = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
            except (ValueError, AttributeError):
                ts_parsed = None
            # AT-URI → web URL: at://<did>/app.bsky.feed.post/<rkey> →
            # https://bsky.app/profile/<handle>/post/<rkey>
            web_url = None
            m = re.search(r"app\.bsky\.feed\.post/([A-Za-z0-9]+)$", uri)
            if m:
                web_url = f"https://bsky.app/profile/{handle}/post/{m.group(1)}"
            signals.append(EnrichmentSignal(
                type="post",
                summary=f"@{handle}: {text}",
                url=web_url,
                timestamp=ts_parsed,
            ))

        if not signals:
            return None

        followers = profile.get("followersCount", 0)
        posts = profile.get("postsCount", 0)
        summary = (
            f"Bluesky @{handle} ({followers} followers, {posts} posts). "
            + ((desc or "")[:140])
        )
        return EnrichmentResult(
            source="bluesky",
            profile_url=f"https://bsky.app/profile/{handle}",
            confidence=hint.confidence,
            discovered=hint.confidence < 1.0,
            signals=signals[:5],
            summary=summary,
        )
