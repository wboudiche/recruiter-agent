"""Background enrichment for LinkedIn-sourced candidates.

LinkedIn intentionally blocks scraping, so the `fetch_linkedin` fetcher
is a stub and the URL add-path normally short-circuits, leaving the
candidate in EXTRACTING / awaiting_paste until the user manually pastes
the profile content.

This module tries one cheap auto-fill before falling back to that flow:
search GitHub for the candidate by name, confirm the GitHub profile's
own `name` field is the same person (token-overlap heuristic), and if so
run the GitHub-flavoured branch of the existing extraction pipeline.

When a confident GitHub match exists, the candidate ends up in `scored`
with skills / location / (sometimes) experience populated. When no match
exists, the candidate stays in `awaiting_paste` — identical to today.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from recruiter.events import EventBus
from recruiter.llm.client import LLMClient
from recruiter.models import Application, Candidate, SettingsRow
from recruiter.pipeline.enrichers.github_by_name import find_github_url_for_name
from recruiter.pipeline.fetchers.github import fetch_github
from recruiter.pipeline.orchestrator import process_application
from recruiter.pipeline.router import RoutedInput

logger = logging.getLogger(__name__)


async def enrich_linkedin_candidate_via_github(
    *,
    application_id: int,
    engine: AsyncEngine,
    llm: LLMClient,
    bus: EventBus,
) -> None:
    """Try to fill in a LinkedIn-only candidate by finding their GitHub.

    Safe to fire-and-forget from a FastAPI BackgroundTask: opens its own
    DB session, never raises out of the task (failures are logged), and
    leaves the candidate in awaiting_paste if no match is found."""
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        app = await session.get(Application, application_id)
        if app is None:
            return
        candidate = await session.get(Candidate, app.candidate_id)
        if candidate is None or not candidate.full_name:
            return
        settings = (
            await session.execute(select(SettingsRow).limit(1))
        ).scalar_one_or_none()
        candidate_name = candidate.full_name
        linkedin_url = candidate.source_url

    try:
        github_url = await find_github_url_for_name(
            candidate_name, settings=settings,
        )
    except Exception as exc:  # never let an enrichment failure surface
        logger.warning("github lookup raised for %r: %s", candidate_name, exc)
        return

    if not github_url:
        logger.info("no github match for %r — staying in awaiting_paste", candidate_name)
        return

    try:
        parsed = await fetch_github(github_url)
    except Exception as exc:
        logger.warning("fetch_github(%s) failed: %s", github_url, exc)
        return

    # Run the same pipeline we use for direct GitHub URL adds. Pass
    # `source_url=None` so the candidate's stored LinkedIn URL is
    # preserved (the orchestrator only overwrites when source_url is set).
    routed = RoutedInput(
        kind="github",
        text=parsed.text,
        source_url=None,
        resume_path=None,
    )
    try:
        await process_application(
            application_id=application_id,
            routed=routed,
            engine=engine,
            llm=llm,
            bus=bus,
        )
    except Exception as exc:
        logger.warning("process_application failed during github enrichment: %s", exc)
        return

    logger.info(
        "enriched LinkedIn candidate %r via github=%s (originating linkedin=%s)",
        candidate_name, github_url, linkedin_url,
    )
