from __future__ import annotations

import asyncio
import logging
from typing import Any

from recruiter.enrichment.provider import _REGISTRY, EnrichmentHint
from recruiter.sourcing.provider import SearchError, SearchProvider, SearchResult

logger = logging.getLogger(__name__)

# Upper bound on simultaneous discovery queries. The loop used to run
# them one after another, so a handful of 30s provider timeouts (SerpAPI's
# ceiling) stretched enrichment past four minutes. Concurrency collapses
# that to roughly one round-trip per batch; the cap keeps a burst of
# ~20 queries from tripping SerpAPI's free-tier rate limit or swamping a
# self-hosted SearXNG.
DISCOVERY_CONCURRENCY = 4


async def discover(
    name: str,
    employer: str,
    *,
    sourcing: SearchProvider | None,
    settings: Any,
) -> list[EnrichmentHint]:
    """Issue per-(provider, domain) `"<name>" "<employer>" site:<domain>`
    queries via the active sourcing provider. Top result per query becomes
    an EnrichmentHint at confidence 0.5.

    Queries run concurrently (bounded by DISCOVERY_CONCURRENCY) but hints
    are returned in registry order, not completion order, so downstream
    behaviour is deterministic.

    Failures (no sourcing configured, per-query SearchError) are
    non-fatal: the function simply returns whatever it managed to collect.
    """
    if sourcing is None:
        return []

    toggles: dict[str, bool] = getattr(settings, "enrichment_sources", None) or {}

    quoted_name = f'"{name}"' if name else ""
    quoted_emp = f' "{employer}"' if employer else ""
    planned: list[tuple[str, str, str]] = []  # (source_name, domain, query)
    for source_name, cls in _REGISTRY.items():
        if toggles.get(source_name, True) is False:
            continue
        for domain in getattr(cls, "domains", None) or []:
            query = f'{quoted_name}{quoted_emp} site:{domain}'.strip()
            planned.append((source_name, domain, query))

    semaphore = asyncio.Semaphore(DISCOVERY_CONCURRENCY)

    async def run_one(domain: str, query: str) -> list[SearchResult]:
        async with semaphore:
            try:
                return await sourcing.search(query, limit=3)
            except SearchError as exc:
                logger.info("discovery query failed for %s: %s", domain, exc)
            except Exception as exc:  # pragma: no cover - defensive
                logger.info("discovery query crashed for %s: %s", domain, exc)
            return []

    outcomes = await asyncio.gather(
        *(run_one(domain, query) for _, domain, query in planned)
    )

    hints: list[EnrichmentHint] = []
    for (source_name, _, _), results in zip(planned, outcomes, strict=True):
        if not results:
            continue
        hints.append(EnrichmentHint(
            url=results[0].url,
            confidence=0.5,
            source=source_name,
            name=name,
            employer=employer or None,
        ))
    return hints
