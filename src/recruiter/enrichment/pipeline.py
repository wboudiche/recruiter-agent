from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from recruiter.enrichment.discovery import discover
from recruiter.enrichment.identity import consolidate
from recruiter.enrichment.provider import (
    _REGISTRY,
    EnrichmentBundle,
    EnrichmentHint,
    EnrichmentResult,
)
from recruiter.sourcing.provider import resolve as resolve_sourcing

logger = logging.getLogger(__name__)

BUNDLE_TTL = timedelta(days=30)


def _resolve_providers(settings: Any, llm: Any) -> list:
    """Build provider instances from the registry. The blog provider needs
    the LLM injected; everything else uses the registry's _instantiate."""
    from recruiter.enrichment.provider import _instantiate

    out = []
    toggles: dict[str, bool] = getattr(settings, "enrichment_sources", None) or {}
    for name, cls in _REGISTRY.items():
        if toggles.get(name, True) is False:
            continue
        if name == "blog":
            if llm is None:
                continue
            try:
                out.append(cls(llm=llm))
            except Exception:
                continue
            continue
        inst = _instantiate(cls, settings)
        if inst is not None:
            out.append(inst)
    return out


def _provider_for_url(url: str, providers: list) -> Any | None:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return None
    # Strict-then-lenient: exact match wins, then suffix match.
    for p in providers:
        if host in (d.lower() for d in (p.domains or [])):
            return p
    for p in providers:
        for d in p.domains or []:
            if host.endswith("." + d.lower()):
                return p
    return None


def _route_blog_fallback(url: str, providers: list) -> Any | None:
    for p in providers:
        if p.name == "blog":
            return p
    return None


async def enrich(
    *,
    candidate: Any,
    job: Any,
    settings: Any,
    llm: Any,
) -> EnrichmentBundle:
    """Top-level enrichment orchestrator. Returns a bundle that can be
    serialised straight onto Application.enrichment."""
    fetched = datetime.now(timezone.utc)

    providers = _resolve_providers(settings, llm)

    # Phase 1: explicit-link hints (confidence 1.0).
    hints: list[EnrichmentHint] = []
    explicit_urls: list[str] = []
    for link in (candidate.links or []):
        url = (link.get("url") if isinstance(link, dict) else getattr(link, "url", None)) or ""
        if not url:
            continue
        explicit_urls.append(url)
        hints.append(EnrichmentHint(url=url, confidence=1.0))

    # Phase 2: discovery (consent-gated).
    if getattr(job, "enrichment_consent", False):
        sourcing = resolve_sourcing(settings)
        employer = ""
        # Best-effort: pull employer from the first experience entry.
        exp = getattr(candidate, "experience", None) or []
        if exp:
            first = exp[0]
            if isinstance(first, dict):
                employer = first.get("company") or ""
            else:
                employer = getattr(first, "company", "") or ""
        try:
            disc_hints = await discover(
                getattr(candidate, "full_name", "") or "",
                employer,
                sourcing=sourcing,
                settings=settings,
            )
        except Exception as exc:
            logger.info("discovery layer failed: %s", exc)
            disc_hints = []
        # Don't double-enrich URLs we already have explicitly.
        existing = {u.lower() for u in explicit_urls}
        for h in disc_hints:
            if h.url and h.url.lower() not in existing:
                hints.append(h)

    # Phase 3: route + fan-out.
    async def _run_one(hint: EnrichmentHint) -> tuple[str, EnrichmentResult | Exception | None]:
        provider = None
        if hint.url:
            provider = _provider_for_url(hint.url, providers)
            if provider is None and hint.confidence >= 1.0:
                provider = _route_blog_fallback(hint.url, providers)
        if provider is None:
            return ("(unrouted)", None)
        try:
            r = await provider.enrich(hint)
            return (provider.name, r)
        except Exception as exc:
            return (provider.name, exc)

    raw = await asyncio.gather(*[_run_one(h) for h in hints], return_exceptions=False)

    # Close async clients.
    for p in providers:
        try:
            await p.aclose()
        except Exception:
            pass

    results: list[EnrichmentResult] = []
    errors: list[dict] = []
    for source, val in raw:
        if isinstance(val, Exception):
            errors.append({"source": source, "error": str(val), "transient": False})
        elif val is not None:
            results.append(val)

    # Phase 4: identity consolidation.
    anchor_urls = list(explicit_urls)
    anchor_emails = []
    if getattr(candidate, "email", None):
        anchor_emails.append(candidate.email)

    consolidated = consolidate(results, anchor_urls=anchor_urls, anchor_emails=anchor_emails)

    return EnrichmentBundle(
        fetched_at=fetched,
        expires_at=fetched + BUNDLE_TTL,
        discovery_consent=bool(getattr(job, "enrichment_consent", False)),
        results=consolidated,
        errors=errors,
    )
