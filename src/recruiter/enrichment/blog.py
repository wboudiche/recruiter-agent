from __future__ import annotations

import logging
import re
from typing import Any, ClassVar

import httpx

from recruiter.enrichment.provider import (
    EnrichmentHint,
    EnrichmentResult,
    EnrichmentSignal,
    register,
)

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)
_MAX_BODY_CHARS = 8000

SYSTEM_PROMPT = (
    "You are summarizing a candidate's personal blog or website page for a "
    "recruiter. Reply with one or two sentences in plain English. Mention "
    "the topic and what the page reveals about the author's technical interests. "
    "Do not invent facts."
)


def _strip(html: str) -> str:
    s = _SCRIPT_RE.sub(" ", html)
    s = _STYLE_RE.sub(" ", s)
    s = _HTML_TAG_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


@register("blog")
class BlogProvider:
    name: ClassVar[str] = "blog"
    # Empty domains list — discovery never routes to this provider; it
    # only handles explicit candidate.links URLs that didn't match anyone.
    domains: ClassVar[list[str]] = []

    def __init__(
        self,
        *,
        llm: Any = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # llm is the existing LLMClient Protocol. Lazy import to avoid
        # circulars during test collection.
        if llm is None:
            from recruiter.llm.client import LLMClient  # noqa: F401
            raise ValueError("BlogProvider requires an LLMClient instance")
        self._llm = llm
        self._client = httpx.AsyncClient(
            transport=transport, timeout=10.0, follow_redirects=True
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        if not hint.url:
            return None

        try:
            r = await self._client.get(hint.url)
        except httpx.HTTPError as exc:
            logger.info("blog fetch failed for %s: %s", hint.url, exc)
            return None
        if r.status_code != 200:
            return None
        ctype = (r.headers.get("content-type") or "").lower()
        if "text/html" not in ctype and "application/xhtml" not in ctype:
            return None

        text = _strip(r.text)
        if not text:
            return None
        text = text[:_MAX_BODY_CHARS]

        from recruiter.llm.client import LLMMessage
        try:
            summary = await self._llm.chat(
                [LLMMessage(role="user", content=f"URL: {hint.url}\n\nPage content:\n{text}")],
                system=SYSTEM_PROMPT,
                max_tokens=300,
                temperature=0.0,
            )
        except Exception as exc:
            logger.info("blog LLM summary failed for %s: %s", hint.url, exc)
            return None

        summary = (summary or "").strip()
        if not summary:
            return None

        signal = EnrichmentSignal(
            type="writing",
            summary=summary[:300],
            url=hint.url,
        )
        return EnrichmentResult(
            source="blog",
            profile_url=hint.url,
            confidence=hint.confidence,
            discovered=hint.confidence < 1.0,
            signals=[signal],
            summary=summary[:500],
        )
