from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import ClassVar

import httpx

from recruiter.enrichment.provider import (
    EnrichmentHint,
    EnrichmentResult,
    EnrichmentSignal,
    register,
)

logger = logging.getLogger(__name__)

SE_BASE = "https://api.stackexchange.com/2.3"


def _user_id_from_url(url: str) -> str | None:
    m = re.search(r"stackoverflow\.com/users/(\d+)", url or "")
    return m.group(1) if m else None


@register("stackoverflow")
class StackOverflowProvider:
    name: ClassVar[str] = "stackoverflow"
    domains: ClassVar[list[str]] = ["stackoverflow.com", "stackexchange.com"]

    def __init__(
        self,
        *,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _params(self, **extra) -> dict:
        out = {"site": "stackoverflow", **extra}
        if self._api_key:
            out["key"] = self._api_key
        return out

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        user_id = _user_id_from_url(hint.url) if hint.url else None
        if not user_id:
            return None

        try:
            user_r = await self._client.get(
                f"{SE_BASE}/users/{user_id}", params=self._params()
            )
            ans_r = await self._client.get(
                f"{SE_BASE}/users/{user_id}/answers",
                params=self._params(pagesize=5, sort="votes", order="desc"),
            )
        except httpx.HTTPError as exc:
            logger.info("stackoverflow fetch failed for %s: %s", user_id, exc)
            return None
        if user_r.status_code != 200 or ans_r.status_code != 200:
            return None
        try:
            users = user_r.json().get("items") or []
            answers = ans_r.json().get("items") or []
        except ValueError:
            return None
        if not users:
            return None

        u = users[0]
        rep = u.get("reputation", 0)
        link = u.get("link") or hint.url
        signals: list[EnrichmentSignal] = []
        signals.append(EnrichmentSignal(
            type="profile",
            summary=f"Stack Overflow: {rep} reputation as {u.get('display_name','user')}",
            url=link,
        ))
        for a in answers[:4]:
            ts = a.get("creation_date")
            ts_parsed = (
                datetime.fromtimestamp(ts, tz=UTC)
                if isinstance(ts, (int, float))
                else None
            )
            tags = ", ".join(a.get("tags") or [])
            accepted = "[accepted] " if a.get("is_accepted") else ""
            signals.append(EnrichmentSignal(
                type="answer",
                summary=f"{accepted}SO answer ({a.get('score',0)} votes)"
                        + (f" tags: {tags}" if tags else ""),
                url=a.get("link"),
                timestamp=ts_parsed,
            ))

        summary = (
            f"Stack Overflow: {rep} rep, {len(answers)} top-voted answers shown."
        )
        return EnrichmentResult(
            source="stackoverflow",
            profile_url=link,
            confidence=hint.confidence,
            discovered=hint.confidence < 1.0,
            signals=signals[:5],
            summary=summary,
        )
