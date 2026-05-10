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


def _username_from_devto_url(url: str) -> str | None:
    m = re.match(r"https?://dev\.to/([A-Za-z0-9_-]+)/?", url or "")
    return m.group(1) if m else None


@register("devto")
class DevToProvider:
    name: ClassVar[str] = "devto"
    domains: ClassVar[list[str]] = ["dev.to"]

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        username = _username_from_devto_url(hint.url) if hint.url else None
        if not username:
            return None

        base = "https://dev.to"
        try:
            user_r = await self._client.get(
                f"{base}/api/users/by_username", params={"url": username}
            )
            arts_r = await self._client.get(
                f"{base}/api/articles", params={"username": username, "per_page": 5}
            )
        except httpx.HTTPError as exc:
            logger.info("devto fetch failed for %s: %s", username, exc)
            return None
        if user_r.status_code != 200 or arts_r.status_code != 200:
            return None
        try:
            user = user_r.json()
            articles = arts_r.json() or []
        except ValueError:
            return None

        signals: list[EnrichmentSignal] = []
        bio = user.get("summary") or ""
        gh = user.get("github_username")
        site = user.get("website_url")
        bio_extra = []
        if gh:
            bio_extra.append(f"github.com/{gh}")
        if site:
            bio_extra.append(site)
        if bio or bio_extra:
            signals.append(EnrichmentSignal(
                type="profile",
                summary=f"Dev.to: {bio} {' '.join(bio_extra)}".strip(),
                url=f"{base}/{username}",
            ))
        for art in articles[:4]:
            ts = art.get("published_at")
            try:
                ts_parsed = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
            except (ValueError, AttributeError):
                ts_parsed = None
            tags = ", ".join(art.get("tag_list") or [])
            signals.append(EnrichmentSignal(
                type="writing",
                summary=f"Dev.to article: \"{art.get('title')}\""
                        + (f" [{tags}]" if tags else "")
                        + f" — {art.get('positive_reactions_count', 0)} reactions",
                url=art.get("url"),
                timestamp=ts_parsed,
            ))

        if not signals:
            return None

        summary = f"Dev.to author {username}; {len(articles)} recent posts."
        return EnrichmentResult(
            source="devto",
            profile_url=f"{base}/{username}",
            confidence=hint.confidence,
            discovered=hint.confidence < 1.0,
            signals=signals[:5],
            summary=summary,
        )
