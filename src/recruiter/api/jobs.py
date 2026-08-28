import inspect
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from recruiter.api.candidates import get_engine_dep, get_event_bus, get_llm
from recruiter.api.deps import get_session, require_user
from recruiter.events import EventBus
from recruiter.llm.client import LLMClient
from recruiter.models import Job, JobStatus
from recruiter.pipeline.criteria_suggester import suggest_criteria
from recruiter.pipeline.orchestrator import rescore_applications_for_job
from recruiter.schemas.job import CriteriaItem, JobCreate, JobRead, JobUpdate
from recruiter.schemas.job_suggest import SuggestCriteriaRequest, SuggestCriteriaResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"], dependencies=[Depends(require_user)])


async def get_llm_or_none(
    request: Request, session: AsyncSession = Depends(get_session)
) -> LLMClient | None:
    """Like `get_llm`, but None instead of a 503 when no provider is
    configured.

    Saving a job's title/status must never fail for lack of an LLM —
    only a criteria change actually needs one (to rescore). Declaring
    `Depends(get_llm)` directly isn't an option: FastAPI resolves it
    eagerly for every request regardless of what the route does with
    it, so its 503 would propagate before the handler ever saw whether
    criteria changed. Consulting `dependency_overrides` directly here
    keeps this testable the same way `Depends(get_llm)` normally is.
    """
    override = request.app.dependency_overrides.get(get_llm)
    if override is not None:
        result = override()
        return await result if inspect.isawaitable(result) else result
    try:
        return await get_llm(session=session)
    except HTTPException:
        return None


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_job(payload: JobCreate, session: AsyncSession = Depends(get_session)) -> JobRead:
    job = Job(
        title=payload.title,
        description=payload.description,
        criteria=[c.model_dump() for c in payload.criteria],
        enrichment_consent=payload.enrichment_consent,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return _to_read(job)


@router.get("", response_model=list[JobRead])
async def list_jobs(session: AsyncSession = Depends(get_session)) -> list[JobRead]:
    rows = (await session.execute(select(Job).order_by(Job.created_at.desc()))).scalars().all()
    return [_to_read(j) for j in rows]


@router.post("/criteria/suggest", response_model=SuggestCriteriaResponse)
async def suggest_criteria_endpoint(
    payload: SuggestCriteriaRequest,
    llm: LLMClient = Depends(get_llm),
) -> SuggestCriteriaResponse:
    try:
        items = await suggest_criteria(
            title=payload.title,
            description=payload.description,
            llm=llm,
        )
    except Exception as exc:
        logger.warning("criteria suggestion failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="Criteria suggestion failed") from exc
    return SuggestCriteriaResponse(criteria=items)


@router.get("/{job_id}", response_model=JobRead)
async def get_job(job_id: int, session: AsyncSession = Depends(get_session)) -> JobRead:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _to_read(job)


@router.patch("/{job_id}", response_model=JobRead)
async def update_job(
    job_id: int,
    payload: JobUpdate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    engine: AsyncEngine = Depends(get_engine_dep),
    llm: LLMClient | None = Depends(get_llm_or_none),
    bus: EventBus = Depends(get_event_bus),
) -> JobRead:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if payload.title is not None:
        job.title = payload.title
    if payload.description is not None:
        job.description = payload.description
    if payload.criteria is not None:
        job.criteria = [c.model_dump() for c in payload.criteria]
    if payload.status is not None:
        job.status = JobStatus(payload.status)
    if payload.enrichment_consent is not None:
        job.enrichment_consent = payload.enrichment_consent
    await session.commit()
    await session.refresh(job)

    if payload.criteria is not None:
        # Existing scores were computed against the old criteria and are
        # now stale. Rescoring calls the LLM once per applicant, so it
        # runs in the background rather than blocking this save.
        if llm is not None:
            background_tasks.add_task(
                rescore_applications_for_job, job_id=job.id, engine=engine, llm=llm, bus=bus,
            )
        else:
            logger.warning(
                "job %s criteria changed but no LLM is configured; skipping rescore", job.id,
            )
    return _to_read(job)


def _to_read(job: Job) -> JobRead:
    return JobRead(
        id=job.id,
        title=job.title,
        description=job.description,
        criteria=[CriteriaItem.model_validate(c) for c in (job.criteria or [])],
        status=job.status.value,
        enrichment_consent=job.enrichment_consent,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
