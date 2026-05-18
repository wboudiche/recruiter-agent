import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from recruiter.api.deps import get_session, require_user
from recruiter.config import get_config
from recruiter.crypto import settings_cipher
from recruiter.db import get_engine
from recruiter.events import EventBus
from recruiter.llm.anthropic import AnthropicLLMClient
from recruiter.llm.client import LLMClient
from recruiter.llm.openai_compat import OpenAICompatLLMClient
from recruiter.models import Application, Candidate, Job, SettingsRow, SourceType, Stage
from recruiter.pipeline.enrichers.linkedin_via_github import (
    enrich_linkedin_candidate_via_github,
)
from recruiter.pipeline.fetchers.github import fetch_github
from recruiter.pipeline.fetchers.linkedin_playwright import fetch_linkedin_playwright
from recruiter.pipeline.fetchers.linkedin_stub import fetch_linkedin
from recruiter.pipeline.fetchers.webpage import fetch_webpage
from recruiter.pipeline.parsers.text import ParsedContent
from recruiter.sourcing.apify import (
    DEFAULT_ACTOR_ID as APIFY_DEFAULT_ACTOR_ID,
    ApifyError,
    fetch_profile_via_apify,
)
from recruiter.sourcing.linkedin_login import login_and_extract_cookie
from recruiter.pipeline.orchestrator import process_application
from recruiter.pipeline.parsers.docx import parse_docx
from recruiter.pipeline.parsers.pdf import parse_pdf
from recruiter.pipeline.router import RoutedInput, classify_url

router = APIRouter(prefix="/api/jobs/{job_id}/candidates", tags=["candidates"], dependencies=[Depends(require_user)])


_singleton_bus = EventBus()


def get_event_bus() -> EventBus:
    return _singleton_bus


async def get_llm(session: AsyncSession = Depends(get_session)) -> LLMClient:
    """Resolve the configured LLM client from the Settings singleton row.

    Returns 503 if the settings row is missing, the provider is unknown, or the
    selected provider's credentials/URL are not yet configured. Tests override
    this dependency via app.dependency_overrides[get_llm] = lambda: FakeLLMClient(...).
    """
    from recruiter.api.settings import _cipher

    row = await session.get(SettingsRow, 1)
    if row is None:
        raise HTTPException(status_code=503, detail="Settings not configured. PUT /api/settings first.")

    provider = row.default_llm_provider
    overrides = row.model_overrides or {}

    if provider == "anthropic":
        if not row.anthropic_api_key_enc:
            raise HTTPException(status_code=503, detail="Anthropic API key not set in settings.")
        api_key = _cipher().decrypt(row.anthropic_api_key_enc)
        return AnthropicLLMClient(
            api_key=api_key,
            model=overrides.get("anthropic_model", "claude-sonnet-4-6"),
        )
    if provider == "local":
        if not row.local_llm_url:
            raise HTTPException(status_code=503, detail="Local LLM URL not set in settings.")
        # Prefer the in-DB encrypted key; fall back to env var (dev escape hatch);
        # finally "not-needed" for truly anonymous local servers (Ollama).
        if row.local_llm_api_key_enc:
            api_key = _cipher().decrypt(row.local_llm_api_key_enc)
        else:
            api_key = get_config().local_llm_api_key or "not-needed"
        return OpenAICompatLLMClient(
            base_url=row.local_llm_url,
            model=overrides.get("local_model", "gpt-oss-120b"),
            api_key=api_key,
        )
    raise HTTPException(status_code=503, detail=f"Unknown LLM provider: {provider}")


def get_engine_dep() -> AsyncEngine:
    return get_engine(get_config().database_url)


class CandidateCreateUrl(BaseModel):
    kind: Literal["url"]
    url: str
    # Optional metadata harvested from the originating sourcing search. We
    # use these to pre-fill `candidate.full_name` / `headline` so that
    # LinkedIn-sourced candidates (which can't be auto-scraped) at least
    # render with a real name on the kanban while awaiting manual paste.
    # For non-LinkedIn URLs these are still useful as a placeholder during
    # the brief background-extraction window.
    name: str | None = Field(default=None, max_length=255)
    snippet: str | None = Field(default=None, max_length=512)


class CandidateCreatePaste(BaseModel):
    kind: Literal["paste"]
    content: str
    source_url: str | None = None


class ApplicationCreated(BaseModel):
    application_id: int


@router.post("", response_model=ApplicationCreated, status_code=status.HTTP_202_ACCEPTED)
async def add_candidate(
    job_id: int,
    payload: CandidateCreateUrl | CandidateCreatePaste,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    engine: AsyncEngine = Depends(get_engine_dep),
    llm: LLMClient = Depends(get_llm),
    bus: EventBus = Depends(get_event_bus),
) -> ApplicationCreated:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    source_url: str | None
    if payload.kind == "url":
        try:
            if classify_url(payload.url) == "linkedin":
                parsed = await _fetch_linkedin(payload.url, session)
                routed = RoutedInput(
                    kind="linkedin", text=parsed.text,
                    source_url=payload.url, resume_path=None,
                )
            else:
                routed = await _route_url(payload.url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        source_type = SourceType.URL
        source_url = payload.url
    else:
        routed = RoutedInput(kind="paste", text=payload.content, source_url=payload.source_url, resume_path=None)
        source_type = SourceType.PASTE
        source_url = payload.source_url

    # Pre-fill name / headline from the originating search result if the
    # client forwarded them. The LLM-driven extractor (if it runs) will
    # later overwrite these with structured profile data — until then,
    # they make the kanban card readable instead of "Candidate #N".
    prefill_name: str | None = None
    prefill_headline: str | None = None
    if payload.kind == "url":
        prefill_name = (payload.name or "").strip() or None
        prefill_headline = (payload.snippet or "").strip() or None
        if prefill_headline and len(prefill_headline) > 512:
            prefill_headline = prefill_headline[:512]

    candidate = Candidate(
        source_type=source_type,
        source_url=source_url,
        full_name=prefill_name,
        headline=prefill_headline,
    )
    session.add(candidate)
    await session.flush()

    application = Application(job_id=job.id, candidate_id=candidate.id, stage=Stage.EXTRACTING)
    session.add(application)
    await session.commit()
    await session.refresh(application)

    if routed.kind == "linkedin" and not routed.text.strip():
        # Either no cookie configured or the cookie was rejected
        # (expired/challenged). Fall back to the GitHub-by-name enricher;
        # no match → stays in awaiting_paste, as before.
        background_tasks.add_task(
            enrich_linkedin_candidate_via_github,
            application_id=application.id,
            engine=engine,
            llm=llm,
            bus=bus,
        )
        return ApplicationCreated(application_id=application.id)

    background_tasks.add_task(
        process_application,
        application_id=application.id,
        routed=routed,
        engine=engine,
        llm=llm,
        bus=bus,
    )
    return ApplicationCreated(application_id=application.id)


async def _route_url(url: str) -> RoutedInput:
    """Routing for github / web. LinkedIn is dispatched separately by
    the handler because it needs DB-session access for cookie reads
    and (optionally) auto-reconnect."""
    kind = classify_url(url)
    if kind == "github":
        parsed = await fetch_github(url)
        return RoutedInput(kind=kind, text=parsed.text, source_url=url, resume_path=None)
    if kind == "linkedin":
        # Caller must use _fetch_linkedin instead — this branch shouldn't
        # be hit, but keep a safe fall-through to the stub.
        parsed = fetch_linkedin(url)
        return RoutedInput(kind=kind, text=parsed.text, source_url=url, resume_path=None)
    parsed = await fetch_webpage(url)
    return RoutedInput(kind=kind, text=parsed.text, source_url=url, resume_path=None)


_EXPIRY_REASONS = {"cookie expired or challenged", "no li_at cookie configured"}


async def _fetch_linkedin(
    url: str, session: AsyncSession,
) -> ParsedContent:
    """Fetch a LinkedIn profile, preferring providers in this order:

      1. Apify's dev_fusion/linkedin-profile-scraper if
         `settings.apify_api_key_enc` is set. Reliable but costs
         ~$0.01/profile. Definitive failures (auth/billing/not-found)
         fall through to Playwright rather than blocking the user on
         a paid provider's outage.
      2. Headless-Chromium Playwright with the configured `li_at`
         cookie. Free but throttled by LinkedIn after burst use.
      3. Auto-reconnect via stored credentials if the cookie is dead
         and the user opted in.

    Anything not auto-resolved (e.g. limited public view, redirect
    loop, missing creds) is returned with `needs_paste=True` so the
    handler falls back to the GitHub-by-name enricher.
    """
    apify_key = await _resolve_apify_key(session)
    if apify_key:
        actor_id = await _resolve_apify_actor_id(session)
        try:
            return await fetch_profile_via_apify(
                url, api_key=apify_key, actor_id=actor_id,
            )
        except ApifyError as exc:
            # Definitive provider failure (bad token, out of credits,
            # not found). Log it, fall through to the Playwright path
            # so the user isn't stuck if Apify runs out of credits.
            logger.warning("apify failed, falling back to playwright: %s", exc)

    li_at = await _resolve_linkedin_cookie(session)
    if not li_at:
        # Try auto-reconnect from stored creds even when there's no
        # current cookie — covers the "user disconnected then a scrape
        # arrives" case.
        new_cookie = await _attempt_auto_reconnect(session)
        if not new_cookie:
            return fetch_linkedin(url)  # stub, empty
        li_at = new_cookie

    pc = await fetch_linkedin_playwright(url, li_at=li_at)
    reason = pc.metadata.get("reason") if pc.metadata else None
    if not pc.metadata or not pc.metadata.get("needs_paste"):
        return pc  # success
    if reason != "cookie expired or challenged":
        return pc  # different failure — don't burn an auto-reconnect on it

    new_cookie = await _attempt_auto_reconnect(session)
    if not new_cookie:
        return pc  # no creds stored, or login failed — caller falls back
    return await fetch_linkedin_playwright(url, li_at=new_cookie)


async def _attempt_auto_reconnect(session: AsyncSession) -> str | None:
    """Re-acquire `li_at` using the stored email + encrypted password.

    Returns the new cookie on success, or None if auto-reconnect isn't
    configured / the login was rejected / the login was challenged. On
    a definitive failure (rejected / challenge presented), clears the
    stored cookie so subsequent reads don't keep retrying with a dead
    cookie — the user is prompted to manually reconnect via the UI.
    """
    row = (
        await session.execute(select(SettingsRow).limit(1))
    ).scalar_one_or_none()
    if row is None or not row.linkedin_email or not row.linkedin_password_enc:
        return None
    try:
        password = settings_cipher().decrypt(row.linkedin_password_enc)
    except Exception:
        return None
    email = row.linkedin_email

    result = await login_and_extract_cookie(email, password)
    if result.status != "connected" or not result.li_at:
        # Drop the now-known-bad cookie so the UI can surface a
        # "Reconnect" prompt. We keep the stored creds — the user may
        # just need to clear a one-off challenge in their browser.
        row.linkedin_li_at_enc = None
        row.linkedin_li_at_set_at = None
        await session.commit()
        return None

    row.linkedin_li_at_enc = settings_cipher().encrypt(result.li_at)
    row.linkedin_li_at_set_at = datetime.now(timezone.utc)
    await session.commit()
    return result.li_at


async def _resolve_apify_key(session: AsyncSession) -> str:
    """Return the decrypted Apify API token, or "" if none configured.
    Errors during decryption are swallowed (treated as "no key").
    """
    row = (
        await session.execute(select(SettingsRow).limit(1))
    ).scalar_one_or_none()
    if row is None or not row.apify_api_key_enc:
        return ""
    try:
        return settings_cipher().decrypt(row.apify_api_key_enc) or ""
    except Exception:
        return ""


async def _resolve_apify_actor_id(session: AsyncSession) -> str:
    """Return the configured Apify actor slug, or the default if
    nothing is set."""
    row = (
        await session.execute(select(SettingsRow).limit(1))
    ).scalar_one_or_none()
    if row is None or not row.apify_actor_id:
        return APIFY_DEFAULT_ACTOR_ID
    return row.apify_actor_id


async def _resolve_linkedin_cookie(session: AsyncSession) -> str:
    """Cookie source priority:

      1. `RECRUITER_LINKEDIN_LI_AT` env var (dev override / single-tenant
         deployments without a Settings UI).
      2. `settings.linkedin_li_at_enc` (encrypted, written by the
         /api/sourcing/linkedin/connect endpoint).

    Returns "" when neither is set; the caller's LinkedIn branch then
    routes to the GitHub-by-name fallback.
    """
    env_cookie = get_config().linkedin_li_at
    if env_cookie:
        return env_cookie
    row = (
        await session.execute(select(SettingsRow).limit(1))
    ).scalar_one_or_none()
    if row is None or not row.linkedin_li_at_enc:
        return ""
    try:
        return settings_cipher().decrypt(row.linkedin_li_at_enc) or ""
    except Exception:
        return ""


@router.post("/upload", response_model=ApplicationCreated, status_code=status.HTTP_202_ACCEPTED)
async def upload_resume(
    job_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    engine: AsyncEngine = Depends(get_engine_dep),
    llm: LLMClient = Depends(get_llm),
    bus: EventBus = Depends(get_event_bus),
) -> ApplicationCreated:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    data = await file.read()
    name = (file.filename or "").lower()
    kind: Literal["pdf", "docx"]
    if name.endswith(".pdf"):
        parsed = parse_pdf(data)
        kind = "pdf"
    elif name.endswith(".docx"):
        parsed = parse_docx(data)
        kind = "docx"
    else:
        raise HTTPException(status_code=415, detail="only .pdf and .docx are accepted")

    storage_dir = Path(get_config().resume_storage_path)
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_path = storage_dir / f"{uuid.uuid4().hex}_{os.path.basename(name)}"
    stored_path.write_bytes(data)

    candidate = Candidate(source_type=SourceType.RESUME, resume_path=str(stored_path))
    session.add(candidate)
    await session.flush()
    application = Application(job_id=job.id, candidate_id=candidate.id, stage=Stage.EXTRACTING)
    session.add(application)
    await session.commit()
    await session.refresh(application)

    routed = RoutedInput(kind=kind, text=parsed.text, source_url=None, resume_path=str(stored_path))
    background_tasks.add_task(
        process_application,
        application_id=application.id,
        routed=routed,
        engine=engine,
        llm=llm,
        bus=bus,
    )
    return ApplicationCreated(application_id=application.id)


class PastePayload(BaseModel):
    content: str


paste_router = APIRouter(prefix="/api/applications", tags=["applications"], dependencies=[Depends(require_user)])


@paste_router.post("/{application_id}/paste", response_model=ApplicationCreated, status_code=status.HTTP_202_ACCEPTED)
async def paste_content(
    application_id: int,
    payload: PastePayload,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    engine: AsyncEngine = Depends(get_engine_dep),
    llm: LLMClient = Depends(get_llm),
    bus: EventBus = Depends(get_event_bus),
) -> ApplicationCreated:
    application = await session.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="application not found")
    if application.stage != Stage.EXTRACTING:
        raise HTTPException(status_code=409, detail=f"cannot paste in stage {application.stage.value}")

    routed = RoutedInput(kind="paste", text=payload.content, source_url=None, resume_path=None)
    background_tasks.add_task(
        process_application,
        application_id=application_id,
        routed=routed,
        engine=engine,
        llm=llm,
        bus=bus,
    )
    return ApplicationCreated(application_id=application_id)
