from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import selectinload

from recruiter.api.candidates import ApplicationCreated, get_engine_dep, get_event_bus, get_llm
from recruiter.api.deps import get_session, require_user
from recruiter.events import EventBus
from recruiter.llm.client import LLMClient
from recruiter.models import Application, Candidate, Stage
from recruiter.pipeline.orchestrator import process_application
from recruiter.pipeline.router import RoutedInput
from recruiter.schemas.application import ApplicationRead, ApplicationUpdate, ScoreBreakdownItem
from recruiter.schemas.candidate import CandidateRead, CandidateUpdate

# Authorization model: shared workspace. Any user authenticated via OIDC and
# accepted by the domain allowlist (`auth.allowlist`) can read and mutate any
# candidate or application — there is no per-record owner check by design.
# If per-user ownership or role tiers (admin/recruiter/viewer) are ever needed,
# add a column on Candidate/Application and a guard alongside `require_user`.
router = APIRouter(prefix="/api", tags=["applications"], dependencies=[Depends(require_user)])


async def _load_application(session: AsyncSession, application_id: int) -> Application | None:
    """Load an application with the candidate eager-loaded so awaiting_paste
    can be computed without a follow-up query."""
    return (
        await session.execute(
            select(Application)
            .where(Application.id == application_id)
            .options(selectinload(Application.candidate))
        )
    ).scalar_one_or_none()


@router.get("/applications/{application_id}", response_model=ApplicationRead)
async def get_application(application_id: int, session: AsyncSession = Depends(get_session)) -> ApplicationRead:
    app_row = await _load_application(session, application_id)
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


@router.patch("/candidates/{candidate_id}", response_model=CandidateRead)
async def update_candidate(
    candidate_id: int,
    payload: CandidateUpdate,
    session: AsyncSession = Depends(get_session),
) -> CandidateRead:
    candidate = await session.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    # `mode="json"` serializes HttpUrl back to plain `str` so the value can
    # be assigned to a String column without coupling the model to Pydantic types.
    data = payload.model_dump(exclude_unset=True, mode="json")
    if "photo_url" in data:
        candidate.photo_url = data["photo_url"] or None
    await session.commit()
    return CandidateRead.model_validate(candidate)


@router.get("/jobs/{job_id}/applications", response_model=list[ApplicationRead])
async def list_applications_for_job(
    job_id: int, session: AsyncSession = Depends(get_session)
) -> list[ApplicationRead]:
    rows = (
        await session.execute(
            select(Application)
            .where(Application.job_id == job_id)
            .order_by(Application.created_at.desc())
            .options(selectinload(Application.candidate))
        )
    ).scalars().all()
    return [_to_read(r) for r in rows]


def _to_read(app_row: Application) -> ApplicationRead:
    breakdown = (
        [ScoreBreakdownItem.model_validate(c) for c in app_row.score_breakdown]
        if app_row.score_breakdown
        else None
    )
    # `awaiting_paste` is the UI's "manual paste required" flag. It's TRUE
    # only for LinkedIn URLs that have been in EXTRACTING long enough that
    # the background Playwright scrape has had time to either finish or
    # fail. Within the first 90 seconds, the system is most likely still
    # actively scraping — flagging awaiting_paste in that window would
    # falsely tell the user to paste manually when auto-extraction is
    # still in progress.
    _now = datetime.now(timezone.utc)
    _created = app_row.created_at
    if _created is not None and _created.tzinfo is None:
        _created = _created.replace(tzinfo=timezone.utc)
    _age_seconds = (_now - _created).total_seconds() if _created else 0
    awaiting_paste = (
        app_row.stage == Stage.EXTRACTING
        and app_row.candidate is not None
        and app_row.candidate.source_url is not None
        and "linkedin.com" in app_row.candidate.source_url.lower()
        and _age_seconds > 90
    )
    return ApplicationRead(
        id=app_row.id,
        job_id=app_row.job_id,
        candidate_id=app_row.candidate_id,
        stage=app_row.stage.value,
        score=app_row.score,
        score_breakdown=breakdown,
        score_rationale=app_row.score_rationale,
        notes=app_row.notes,
        validated_at=app_row.validated_at,
        invited_at=app_row.invited_at,
        scheduled_at=app_row.scheduled_at,
        rejected_at=app_row.rejected_at,
        created_at=app_row.created_at,
        updated_at=app_row.updated_at,
        awaiting_paste=awaiting_paste,
        enrichment=app_row.enrichment,
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
    app_row = await _load_application(session, application_id)
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
    # Ensure candidate is loaded for awaiting_paste computation.
    await session.refresh(app_row, attribute_names=["candidate"])
    return _to_read(app_row)



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


@router.post(
    "/applications/{application_id}/re-enrich",
    response_model=ApplicationCreated,
    status_code=202,
)
async def re_enrich_application(
    application_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    engine: AsyncEngine = Depends(get_engine_dep),
    llm: LLMClient = Depends(get_llm),
    bus: EventBus = Depends(get_event_bus),
) -> ApplicationCreated:
    """Clear the cached enrichment bundle and re-run the pipeline starting
    at Stage.ENRICHING. The orchestrator will see `enrichment` is None and
    re-fetch fresh."""
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")

    candidate = await session.get(Candidate, app_row.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")

    app_row.enrichment = None
    app_row.stage = Stage.ENRICHING
    await session.commit()

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
