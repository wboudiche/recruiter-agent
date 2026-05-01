import os
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from recruiter.api.deps import get_session
from recruiter.config import get_config
from recruiter.db import get_engine
from recruiter.events import EventBus
from recruiter.llm.anthropic import AnthropicLLMClient
from recruiter.llm.client import LLMClient
from recruiter.llm.openai_compat import OpenAICompatLLMClient
from recruiter.models import Application, Candidate, Job, SettingsRow, SourceType, Stage
from recruiter.pipeline.fetchers.github import fetch_github
from recruiter.pipeline.fetchers.linkedin_stub import fetch_linkedin
from recruiter.pipeline.fetchers.webpage import fetch_webpage
from recruiter.pipeline.orchestrator import process_application
from recruiter.pipeline.parsers.docx import parse_docx
from recruiter.pipeline.parsers.pdf import parse_pdf
from recruiter.pipeline.router import RoutedInput, classify_url

router = APIRouter(prefix="/api/jobs/{job_id}/candidates", tags=["candidates"])


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
        return OpenAICompatLLMClient(
            base_url=row.local_llm_url,
            model=overrides.get("local_model", "gpt-oss-120b"),
            api_key=get_config().local_llm_api_key or "not-needed",
        )
    raise HTTPException(status_code=503, detail=f"Unknown LLM provider: {provider}")


def get_engine_dep() -> AsyncEngine:
    return get_engine(get_config().database_url)


class CandidateCreateUrl(BaseModel):
    kind: Literal["url"]
    url: str


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

    if payload.kind == "url":
        try:
            routed = await _route_url(payload.url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        source_type = SourceType.URL
        source_url = payload.url
    else:
        routed = RoutedInput(kind="paste", text=payload.content, source_url=payload.source_url, resume_path=None)
        source_type = SourceType.PASTE
        source_url = payload.source_url

    candidate = Candidate(source_type=source_type, source_url=source_url)
    session.add(candidate)
    await session.flush()

    application = Application(job_id=job.id, candidate_id=candidate.id, stage=Stage.EXTRACTING)
    session.add(application)
    await session.commit()
    await session.refresh(application)

    if routed.kind == "linkedin":
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
    kind = classify_url(url)
    if kind == "github":
        parsed = await fetch_github(url)
        return RoutedInput(kind=kind, text=parsed.text, source_url=url, resume_path=None)
    if kind == "linkedin":
        parsed = fetch_linkedin(url)
        return RoutedInput(kind=kind, text=parsed.text, source_url=url, resume_path=None)
    parsed = await fetch_webpage(url)
    return RoutedInput(kind=kind, text=parsed.text, source_url=url, resume_path=None)


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


paste_router = APIRouter(prefix="/api/applications", tags=["applications"])


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
