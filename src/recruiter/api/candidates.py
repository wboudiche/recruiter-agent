from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from recruiter.api.deps import get_session
from recruiter.config import get_config
from recruiter.db import get_engine
from recruiter.events import EventBus
from recruiter.llm.client import LLMClient
from recruiter.models import Application, Candidate, Job, SourceType, Stage
from recruiter.pipeline.fetchers.github import fetch_github
from recruiter.pipeline.fetchers.linkedin_stub import fetch_linkedin
from recruiter.pipeline.fetchers.webpage import fetch_webpage
from recruiter.pipeline.orchestrator import process_application
from recruiter.pipeline.router import RoutedInput, classify_url

router = APIRouter(prefix="/api/jobs/{job_id}/candidates", tags=["candidates"])


_singleton_bus = EventBus()


def get_event_bus() -> EventBus:
    return _singleton_bus


def get_llm() -> LLMClient:
    raise HTTPException(status_code=500, detail="LLM client not configured for this environment")


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
        routed = await _route_url(payload.url)
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
