from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import ClassVar
from urllib.parse import urlparse

import httpx

from recruiter.enrichment.provider import (
    EnrichmentHint,
    EnrichmentResult,
    EnrichmentSignal,
    register,
)

logger = logging.getLogger(__name__)

KNOWN_INSTANCES: list[str] = [
    "mastodon.social",
    "fosstodon.org",
    "hachyderm.io",
    "mas.to",
    "infosec.exchange",
    "techhub.social",
    "sigmoid.social",
]

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str) -> str:
    return _HTML_TAG_RE.sub("", s or "").strip()


def _parse_mastodon_url(url: str) -> tuple[str, str] | None:
    """Return (instance, username) for a Mastodon profile URL, or None."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host not in KNOWN_INSTANCES:
        return None
    path = parsed.path.strip("/")
    if not path.startswith("@"):
        return None
    user = path[1:].split("/")[0]
    return (host, user) if user else None


@register("mastodon")
class MastodonProvider:
    name: ClassVar[str] = "mastodon"
    domains: ClassVar[list[str]] = list(KNOWN_INSTANCES)

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        if not hint.url:
            return None
        parsed = _parse_mastodon_url(hint.url)
        if not parsed:
            return None
        instance, username = parsed
        base = f"https://{instance}"

        try:
            lookup = await self._client.get(
                f"{base}/api/v1/accounts/lookup", params={"acct": username}
            )
        except httpx.HTTPError as exc:
            logger.info("mastodon lookup failed for %s@%s: %s", username, instance, exc)
            return None
        if lookup.status_code != 200:
            logger.info("mastodon lookup %s for %s@%s", lookup.status_code, username, instance)
            return None
        try:
            account = lookup.json()
        except ValueError:
            return None
        acct_id = account.get("id")
        if not acct_id:
            return None

        try:
            statuses = await self._client.get(
                f"{base}/api/v1/accounts/{acct_id}/statuses", params={"limit": 5}
            )
        except httpx.HTTPError as exc:
            logger.info("mastodon statuses failed for %s: %s", acct_id, exc)
            return None
        if statuses.status_code != 200:
            return None
        try:
            posts = statuses.json() or []
        except ValueError:
            return None

        signals: list[EnrichmentSignal] = []
        note = _strip_html(account.get("note") or "")
        if note:
            signals.append(EnrichmentSignal(
                type="profile",
                summary=f"Mastodon bio: {note[:200]}",
                url=account.get("url"),
            ))
        for s in posts[:4]:
            content = _strip_html(s.get("content") or "")[:160]
            ts = s.get("created_at")
            try:
                ts_parsed = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
            except (ValueError, AttributeError):
                ts_parsed = None
            signals.append(EnrichmentSignal(
                type="post",
                summary=f"@{username}@{instance}: {content}",
                url=s.get("url"),
                timestamp=ts_parsed,
            ))

        if not signals:
            return None

        followers = account.get("followers_count", 0)
        st_count = account.get("statuses_count", 0)
        summary = (
            f"Mastodon @{username}@{instance} ({followers} followers, {st_count} posts). "
            + (note[:140] if note else "")
        )
        return EnrichmentResult(
            source="mastodon",
            profile_url=account.get("url") or f"{base}/@{username}",
            confidence=hint.confidence,
            discovered=hint.confidence < 1.0,
            signals=signals[:5],
            summary=summary,
        )
