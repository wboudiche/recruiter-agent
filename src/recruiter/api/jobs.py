from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.deps import get_session, require_user
from recruiter.models import Job, JobStatus
from recruiter.schemas.job import JobCreate, JobRead, JobUpdate

router = APIRouter(prefix="/api/jobs", tags=["jobs"], dependencies=[Depends(require_user)])


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_job(payload: JobCreate, session: AsyncSession = Depends(get_session)) -> JobRead:
    job = Job(
        title=payload.title,
        description=payload.description,
        criteria=[c.model_dump() for c in payload.criteria],
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return _to_read(job)


@router.get("", response_model=list[JobRead])
async def list_jobs(session: AsyncSession = Depends(get_session)) -> list[JobRead]:
    rows = (await session.execute(select(Job).order_by(Job.created_at.desc()))).scalars().all()
    return [_to_read(j) for j in rows]


@router.get("/{job_id}", response_model=JobRead)
async def get_job(job_id: int, session: AsyncSession = Depends(get_session)) -> JobRead:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _to_read(job)


@router.patch("/{job_id}", response_model=JobRead)
async def update_job(
    job_id: int, payload: JobUpdate, session: AsyncSession = Depends(get_session)
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
    await session.commit()
    await session.refresh(job)
    return _to_read(job)


def _to_read(job: Job) -> JobRead:
    return JobRead(
        id=job.id,
        title=job.title,
        description=job.description,
        criteria=job.criteria,
        status=job.status.value,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
