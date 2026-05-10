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

TW_BASE = "https://api.twitter.com/2"


def _handle_from_url(url: str) -> str | None:
    m = re.search(r"(?:twitter\.com|x\.com)/([A-Za-z0-9_]{1,15})", url or "")
    if not m:
        return None
    handle = m.group(1)
    if handle in {"i", "search", "home", "explore", "notifications"}:
        return None
    return handle


@register("twitter")
class TwitterProvider:
    name: ClassVar[str] = "twitter"
    domains: ClassVar[list[str]] = ["twitter.com", "x.com"]

    def __init__(
        self,
        *,
        bearer_token: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._bearer = bearer_token
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._bearer}"}

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        handle = _handle_from_url(hint.url) if hint.url else None
        if not handle:
            return None

        try:
            user_r = await self._client.get(
                f"{TW_BASE}/users/by/username/{handle}",
                headers=self._headers(),
                params={"user.fields": "description,public_metrics,url"},
            )
        except httpx.HTTPError as exc:
            logger.info("twitter user fetch failed for %s: %s", handle, exc)
            return None
        if user_r.status_code != 200:
            logger.info("twitter user fetch %s for %s", user_r.status_code, handle)
            return None
        try:
            user_data = user_r.json().get("data") or {}
        except ValueError:
            return None
        if not user_data.get("id"):
            return None
        uid = user_data["id"]

        try:
            tw_r = await self._client.get(
                f"{TW_BASE}/users/{uid}/tweets",
                headers=self._headers(),
                params={
                    "max_results": 5,
                    "tweet.fields": "created_at,public_metrics",
                },
            )
        except httpx.HTTPError as exc:
            logger.info("twitter tweets fetch failed for %s: %s", uid, exc)
            return None
        if tw_r.status_code != 200:
            return None
        try:
            tweets = tw_r.json().get("data") or []
        except ValueError:
            return None

        signals: list[EnrichmentSignal] = []
        desc = user_data.get("description") or ""
        site = user_data.get("url") or ""
        metrics = user_data.get("public_metrics") or {}
        signals.append(EnrichmentSignal(
            type="profile",
            summary=f"X/Twitter @{handle}: {metrics.get('followers_count',0)} followers, "
                    f"{metrics.get('tweet_count',0)} posts."
                    + (f" Bio: {desc[:200]}" if desc else "")
                    + (f" {site}" if site else ""),
            url=f"https://x.com/{handle}",
        ))
        for t in tweets[:4]:
            ts = t.get("created_at")
            try:
                ts_parsed = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
            except (ValueError, AttributeError):
                ts_parsed = None
            m = t.get("public_metrics") or {}
            signals.append(EnrichmentSignal(
                type="post",
                summary=f"@{handle}: {(t.get('text') or '')[:160]} "
                        f"({m.get('like_count',0)} likes, {m.get('retweet_count',0)} RTs)",
                url=f"https://x.com/{handle}/status/{t.get('id')}" if t.get("id") else None,
                timestamp=ts_parsed,
            ))

        summary = f"X/Twitter @{handle}: {metrics.get('followers_count',0)} followers."
        return EnrichmentResult(
            source="twitter",
            profile_url=f"https://x.com/{handle}",
            confidence=hint.confidence,
            discovered=hint.confidence < 1.0,
            signals=signals[:5],
            summary=summary,
        )
