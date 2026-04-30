from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.deps import get_session
from recruiter.models import Application, Candidate, Stage
from recruiter.schemas.application import ApplicationRead, ApplicationUpdate
from recruiter.schemas.candidate import CandidateRead

router = APIRouter(prefix="/api", tags=["applications"])


@router.get("/applications/{application_id}", response_model=ApplicationRead)
async def get_application(application_id: int, session: AsyncSession = Depends(get_session)) -> ApplicationRead:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    return _to_read(app_row)


@router.get("/candidates/{candidate_id}", response_model=CandidateRead)
async def get_candidate(
    candidate_id: int, session: AsyncSession = Depends(get_session)
) -> CandidateRead:
    candidate = await session.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return CandidateRead.model_validate(candidate)


@router.get("/jobs/{job_id}/applications", response_model=list[ApplicationRead])
async def list_applications_for_job(
    job_id: int, session: AsyncSession = Depends(get_session)
) -> list[ApplicationRead]:
    rows = (
        await session.execute(
            select(Application).where(Application.job_id == job_id).order_by(Application.created_at.desc())
        )
    ).scalars().all()
    return [_to_read(r) for r in rows]


def _to_read(app_row: Application) -> ApplicationRead:
    return ApplicationRead(
        id=app_row.id,
        job_id=app_row.job_id,
        candidate_id=app_row.candidate_id,
        stage=app_row.stage.value,
        score=app_row.score,
        score_breakdown=app_row.score_breakdown,
        score_rationale=app_row.score_rationale,
        notes=app_row.notes,
        validated_at=app_row.validated_at,
        invited_at=app_row.invited_at,
        scheduled_at=app_row.scheduled_at,
        rejected_at=app_row.rejected_at,
        created_at=app_row.created_at,
        updated_at=app_row.updated_at,
    )


_TERMINAL_AFTER_INVITED = {Stage.INVITED, Stage.SCHEDULED}


def _validate_transition(current: Stage, target: Stage) -> None:
    """Enforce business rules. Raises HTTPException(409) on illegal transitions."""
    if current in _TERMINAL_AFTER_INVITED and target != Stage.REJECTED:
        raise HTTPException(
            status_code=409,
            detail=f"cannot move from {current.value} to {target.value} after invitation sent",
        )
    if target == Stage.SCORED and current != Stage.VALIDATED:
        raise HTTPException(
            status_code=409,
            detail=f"cannot unvalidate from stage {current.value}",
        )
    if target == Stage.VALIDATED and current != Stage.SCORED:
        raise HTTPException(
            status_code=409,
            detail=f"cannot validate from stage {current.value}",
        )
    if target == Stage.REJECTED and current == Stage.REJECTED:
        raise HTTPException(status_code=409, detail="already rejected")


@router.patch("/applications/{application_id}", response_model=ApplicationRead)
async def patch_application(
    application_id: int,
    payload: ApplicationUpdate,
    session: AsyncSession = Depends(get_session),
) -> ApplicationRead:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")

    if payload.notes is not None:
        app_row.notes = payload.notes

    if payload.stage is not None:
        new_stage = Stage(payload.stage)
        _validate_transition(app_row.stage, new_stage)
        app_row.stage = new_stage
        now = datetime.now(timezone.utc)
        if new_stage == Stage.VALIDATED:
            app_row.validated_at = now
        elif new_stage == Stage.REJECTED:
            app_row.rejected_at = now
        elif new_stage == Stage.SCORED:
            app_row.validated_at = None

    await session.commit()
    await session.refresh(app_row)
    return _to_read(app_row)


from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncEngine

from recruiter.api.candidates import ApplicationCreated, get_engine_dep, get_event_bus, get_llm
from recruiter.events import EventBus
from recruiter.llm.client import LLMClient
from recruiter.models import Candidate
from recruiter.pipeline.orchestrator import process_application
from recruiter.pipeline.router import RoutedInput


@router.post("/applications/{application_id}/retry", response_model=ApplicationCreated, status_code=202)
async def retry_application(
    application_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    engine: AsyncEngine = Depends(get_engine_dep),
    llm: LLMClient = Depends(get_llm),
    bus: EventBus = Depends(get_event_bus),
) -> ApplicationCreated:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    if app_row.stage != Stage.EXTRACTING:
        raise HTTPException(status_code=409, detail=f"cannot retry from stage {app_row.stage.value}")

    candidate = await session.get(Candidate, app_row.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")

    raw_text = ""
    if candidate.raw_extracted and isinstance(candidate.raw_extracted, dict):
        raw_text = candidate.raw_extracted.get("text", "") or ""

    routed = RoutedInput(
        kind="paste",
        text=raw_text,
        source_url=candidate.source_url,
        resume_path=candidate.resume_path,
    )
    background_tasks.add_task(
        process_application,
        application_id=application_id,
        routed=routed,
        engine=engine,
        llm=llm,
        bus=bus,
    )
    return ApplicationCreated(application_id=application_id)
