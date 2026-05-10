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

YT_BASE = "https://www.googleapis.com/youtube/v3"


def _handle_from_url(url: str) -> str | None:
    m = re.search(r"youtube\.com/(@[A-Za-z0-9._-]+)", url or "")
    return m.group(1) if m else None


@register("youtube")
class YouTubeProvider:
    name: ClassVar[str] = "youtube"
    domains: ClassVar[list[str]] = ["youtube.com", "www.youtube.com"]

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

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        handle = _handle_from_url(hint.url) if hint.url else None
        if not handle:
            return None

        try:
            ch_r = await self._client.get(
                f"{YT_BASE}/channels",
                params={
                    "part": "snippet,statistics",
                    "forHandle": handle,
                    "key": self._api_key,
                },
            )
        except httpx.HTTPError as exc:
            logger.info("youtube channels failed for %s: %s", handle, exc)
            return None
        if ch_r.status_code != 200:
            return None
        try:
            items = ch_r.json().get("items") or []
        except ValueError:
            return None
        if not items:
            return None

        ch = items[0]
        channel_id = ch.get("id")
        snip = ch.get("snippet") or {}
        stats = ch.get("statistics") or {}

        try:
            sr_r = await self._client.get(
                f"{YT_BASE}/search",
                params={
                    "part": "snippet",
                    "channelId": channel_id,
                    "maxResults": 5,
                    "order": "date",
                    "type": "video",
                    "key": self._api_key,
                },
            )
        except httpx.HTTPError as exc:
            logger.info("youtube search failed for %s: %s", channel_id, exc)
            return None
        if sr_r.status_code != 200:
            return None
        try:
            videos = sr_r.json().get("items") or []
        except ValueError:
            return None

        signals: list[EnrichmentSignal] = []
        signals.append(EnrichmentSignal(
            type="profile",
            summary=f"YouTube channel {snip.get('title','')}: "
                    f"{stats.get('subscriberCount','?')} subscribers, "
                    f"{stats.get('videoCount','?')} videos."
                    + (f" {snip.get('description','')[:140]}" if snip.get("description") else ""),
            url=f"https://www.youtube.com/{handle}",
        ))
        for v in videos[:4]:
            vsnip = v.get("snippet") or {}
            vid = (v.get("id") or {}).get("videoId")
            ts = vsnip.get("publishedAt")
            try:
                ts_parsed = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
            except (ValueError, AttributeError):
                ts_parsed = None
            desc = vsnip.get("description") or ""
            signals.append(EnrichmentSignal(
                type="talk",
                summary=f"YouTube: \"{vsnip.get('title','')}\""
                        + (f" — {desc[:120]}" if desc else ""),
                url=f"https://www.youtube.com/watch?v={vid}" if vid else None,
                timestamp=ts_parsed,
            ))

        summary = (
            f"YouTube channel {snip.get('title','')} ({handle}): "
            f"{stats.get('subscriberCount','?')} subs."
        )
        return EnrichmentResult(
            source="youtube",
            profile_url=f"https://www.youtube.com/{handle}",
            confidence=hint.confidence,
            discovered=hint.confidence < 1.0,
            signals=signals[:5],
            summary=summary,
        )
