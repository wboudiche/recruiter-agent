from __future__ import annotations

import logging
from typing import Any

from recruiter.enrichment.provider import _REGISTRY, EnrichmentHint
from recruiter.sourcing.provider import SearchError, SearchProvider

logger = logging.getLogger(__name__)


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

    Failures (no sourcing configured, per-query SearchError) are
    non-fatal: the function simply returns whatever it managed to collect.
    """
    if sourcing is None:
        return []

    toggles: dict[str, bool] = getattr(settings, "enrichment_sources", None) or {}

    hints: list[EnrichmentHint] = []
    for source_name, cls in _REGISTRY.items():
        if toggles.get(source_name, True) is False:
            continue
        domains = getattr(cls, "domains", None) or []
        for domain in domains:
            quoted_name = f'"{name}"' if name else ""
            quoted_emp = f' "{employer}"' if employer else ""
            query = f'{quoted_name}{quoted_emp} site:{domain}'.strip()
            try:
                results = await sourcing.search(query, limit=3)
            except SearchError as exc:
                logger.info("discovery query failed for %s: %s", domain, exc)
                continue
            except Exception as exc:  # pragma: no cover - defensive
                logger.info("discovery query crashed for %s: %s", domain, exc)
                continue
            if not results:
                continue
            top = results[0]
            hints.append(EnrichmentHint(
                url=top.url,
                confidence=0.5,
                source=source_name,
                name=name,
                employer=employer or None,
            ))
    return hints
