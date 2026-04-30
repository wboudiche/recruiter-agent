from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.candidates import get_llm
from recruiter.api.deps import get_session
from recruiter.llm.client import LLMClient
from recruiter.models import Application, Candidate, Job, SettingsRow
from recruiter.pipeline.email_drafter import draft_email
from recruiter.schemas.candidate import EducationItem, ExperienceItem, LinkItem
from recruiter.schemas.extraction import ExtractedCandidate
from recruiter.schemas.notification import DraftedEmail, Slot

router = APIRouter(prefix="/api/applications", tags=["notifications"])


class DraftRequest(BaseModel):
    slots: list[Slot]


def _candidate_to_extracted(c: Candidate) -> ExtractedCandidate:
    return ExtractedCandidate(
        full_name=c.full_name,
        email=c.email,
        phone=c.phone,
        location=c.location,
        headline=c.headline,
        summary=c.summary,
        skills=c.skills or [],
        experience=[ExperienceItem(**e) for e in (c.experience or [])],
        education=[EducationItem(**e) for e in (c.education or [])],
        links=[LinkItem(**l) for l in (c.links or [])],
    )


@router.post("/{application_id}/draft-email", response_model=DraftedEmail)
async def draft_email_endpoint(
    application_id: int,
    payload: DraftRequest,
    session: AsyncSession = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
) -> DraftedEmail:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")

    job = await session.get(Job, app_row.job_id)
    candidate = await session.get(Candidate, app_row.candidate_id)
    if job is None or candidate is None:
        raise HTTPException(status_code=404, detail="job or candidate missing")

    settings = await session.get(SettingsRow, 1)
    recruiter_name = (settings.recruiter_name if settings else None) or "the team"
    recruiter_email = (
        settings.recruiter_email if settings else None
    ) or "no-reply@example.com"

    return await draft_email(
        recruiter_name=recruiter_name,
        recruiter_email=recruiter_email,
        company="our team",
        job_title=job.title,
        candidate=_candidate_to_extracted(candidate),
        slots=payload.slots,
        llm=llm,
    )
