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

GH_BASE = "https://api.github.com"


def _username_from_gh_url(url: str) -> str | None:
    m = re.match(r"https?://github\.com/([A-Za-z0-9_-]+)/?$", (url or "").rstrip("/"))
    return m.group(1) if m else None


@register("github")
class GitHubEnrichmentProvider:
    """Per-user enrichment fetcher. Distinct from `recruiter.sourcing.github`,
    which is a search engine. Reuses the same `github_token_enc` setting."""

    name: ClassVar[str] = "github"
    domains: ClassVar[list[str]] = ["github.com"]

    def __init__(
        self,
        *,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = token
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/vnd.github+json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        username = _username_from_gh_url(hint.url) if hint.url else None
        if not username:
            return None

        try:
            user_r = await self._client.get(
                f"{GH_BASE}/users/{username}", headers=self._headers()
            )
            repo_r = await self._client.get(
                f"{GH_BASE}/users/{username}/repos",
                headers=self._headers(),
                params={"per_page": 5, "sort": "updated"},
            )
        except httpx.HTTPError as exc:
            logger.info("github enrichment failed for %s: %s", username, exc)
            return None
        if user_r.status_code != 200 or repo_r.status_code != 200:
            logger.info(
                "github enrichment status %s/%s for %s",
                user_r.status_code, repo_r.status_code, username,
            )
            return None
        try:
            user = user_r.json()
            repos = repo_r.json() or []
        except ValueError:
            return None

        signals: list[EnrichmentSignal] = []
        bio = user.get("bio") or ""
        company = user.get("company") or ""
        email = user.get("email") or ""
        blog = user.get("blog") or ""
        prof_extra = " ".join(p for p in [company, email, blog] if p)
        signals.append(EnrichmentSignal(
            type="profile",
            summary=f"GitHub @{username}: {user.get('public_repos',0)} repos, "
                    f"{user.get('followers',0)} followers"
                    + (f". Bio: {bio}" if bio else "")
                    + (f". {prof_extra}" if prof_extra else ""),
            url=user.get("html_url") or f"https://github.com/{username}",
        ))
        for repo in repos[:4]:
            ts = repo.get("pushed_at")
            try:
                ts_parsed = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
            except (ValueError, AttributeError):
                ts_parsed = None
            lang = repo.get("language") or "Other"
            stars = repo.get("stargazers_count", 0)
            desc = repo.get("description") or ""
            signals.append(EnrichmentSignal(
                type="code",
                summary=f"{repo.get('name')} [{lang}, {stars} stars]"
                        + (f": {desc[:120]}" if desc else ""),
                url=repo.get("html_url"),
                timestamp=ts_parsed,
            ))

        summary = (
            f"GitHub @{username}: {user.get('public_repos',0)} public repos, "
            f"{user.get('followers',0)} followers."
        )
        return EnrichmentResult(
            source="github",
            profile_url=user.get("html_url") or f"https://github.com/{username}",
            confidence=hint.confidence,
            discovered=hint.confidence < 1.0,
            signals=signals[:5],
            summary=summary,
        )
