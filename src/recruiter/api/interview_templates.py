"""Org-wide interview templates — "Technical", "RH screen".

Managed by admins and recruiters; viewers are refused by the /api router's
viewer read-only guard, which this router inherits by being registered on
`_api_router` in main.py. Templates are archived (`is_active=false`), never
deleted: kits hold their own snapshot, and archiving frees the name.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.deps import get_session, require_user
from recruiter.models import InterviewTemplate
from recruiter.schemas.interview_template import (
    InterviewTemplateCreate,
    InterviewTemplateRead,
    InterviewTemplateUpdate,
    TemplateQuestion,
)

router = APIRouter(
    prefix="/api/interview-templates", tags=["interview"], dependencies=[Depends(require_user)],
)

# Fields that may not be set to null through PATCH; only `description` can.
_REQUIRED = {"name", "questions", "probe_mode", "include_job_questions", "is_active"}


def _check_ids(questions: list[TemplateQuestion]) -> None:
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="duplicate question ids")


async def _commit_or_conflict(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="an active template already has that name",
        ) from exc


@router.get("", response_model=list[InterviewTemplateRead])
async def list_templates(
    include_archived: bool = False, session: AsyncSession = Depends(get_session),
) -> list[InterviewTemplate]:
    stmt = select(InterviewTemplate).order_by(InterviewTemplate.name)
    if not include_archived:
        stmt = stmt.where(InterviewTemplate.is_active.is_(True))
    return list((await session.execute(stmt)).scalars().all())


@router.post("", response_model=InterviewTemplateRead, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: InterviewTemplateCreate, session: AsyncSession = Depends(get_session),
) -> InterviewTemplate:
    _check_ids(payload.questions)
    tpl = InterviewTemplate(
        name=payload.name,
        description=payload.description,
        questions=[q.model_dump() for q in payload.questions],
        probe_mode=payload.probe_mode,
        include_job_questions=payload.include_job_questions,
    )
    session.add(tpl)
    await _commit_or_conflict(session)
    await session.refresh(tpl)
    return tpl


@router.patch("/{template_id}", response_model=InterviewTemplateRead)
async def update_template(
    template_id: int,
    payload: InterviewTemplateUpdate,
    session: AsyncSession = Depends(get_session),
) -> InterviewTemplate:
    tpl = await session.get(InterviewTemplate, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="template not found")
    for field in payload.model_fields_set:
        value = getattr(payload, field)
        if value is None and field in _REQUIRED:
            raise HTTPException(status_code=422, detail=f"{field} cannot be null")
        if field == "questions":
            _check_ids(value)
            value = [q.model_dump() for q in value]
        setattr(tpl, field, value)
    await _commit_or_conflict(session)
    await session.refresh(tpl)
    return tpl
