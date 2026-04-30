import smtplib
from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.candidates import get_llm
from recruiter.api.deps import get_session
from recruiter.api.settings import get_smtp_config
from recruiter.llm.client import LLMClient
from recruiter.models import (
    Application,
    Candidate,
    Job,
    Notification,
    NotificationChannel,
    NotificationProvider,
    NotificationStatus,
    SettingsRow,
    Stage,
)
from recruiter.notifications.smtp import SmtpConfig, SmtpNotifier
from recruiter.pipeline.email_drafter import draft_email
from recruiter.schemas.candidate import EducationItem, ExperienceItem, LinkItem
from recruiter.schemas.extraction import ExtractedCandidate
from recruiter.schemas.notification import DraftedEmail, NotifyPayload, Slot

router = APIRouter(prefix="/api/applications", tags=["notifications"])


def get_smtp_factory() -> Callable[[str, int], smtplib.SMTP]:
    """FastAPI dep — override in tests to inject a fake SMTP client."""
    return lambda host, port: smtplib.SMTP(host, port)


class DraftRequest(BaseModel):
    slots: list[Slot]


class NotifyResponse(BaseModel):
    notification_id: int
    external_id: str


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


@router.post(
    "/{application_id}/notify",
    response_model=NotifyResponse,
    status_code=status.HTTP_200_OK,
)
async def notify_endpoint(
    application_id: int,
    payload: NotifyPayload,
    session: AsyncSession = Depends(get_session),
    smtp_factory: Callable[[str, int], smtplib.SMTP] = Depends(get_smtp_factory),
) -> NotifyResponse:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    if app_row.stage != Stage.VALIDATED:
        raise HTTPException(
            status_code=409,
            detail=f"cannot notify from stage {app_row.stage.value} — must be validated",
        )

    candidate = await session.get(Candidate, app_row.candidate_id)
    if candidate is None or not candidate.email:
        raise HTTPException(
            status_code=422,
            detail="candidate email is required to send notification",
        )

    settings = await session.get(SettingsRow, 1)

    if payload.channel == "smtp":
        smtp_cfg_input = get_smtp_config(settings) if settings else None
        if smtp_cfg_input is None:
            raise HTTPException(
                status_code=503, detail="SMTP config not set in settings"
            )
        cfg = SmtpConfig(
            host=smtp_cfg_input.host,
            port=smtp_cfg_input.port,
            user=smtp_cfg_input.user,
            password=smtp_cfg_input.password,
            from_email=smtp_cfg_input.from_email,
            use_starttls=smtp_cfg_input.use_starttls,
        )
        notifier = SmtpNotifier(cfg, smtp_factory=smtp_factory)
    else:
        # gmail path lands in Plan C tasks 13-22
        raise HTTPException(
            status_code=501, detail="Gmail channel not yet wired — see Plan C tasks 13-22"
        )

    receipt = await notifier.send_invitation(
        to_email=candidate.email,
        subject=payload.subject,
        body=payload.body,
        slots=payload.slots,
    )

    now = datetime.now(timezone.utc)
    notification = Notification(
        application_id=application_id,
        channel=NotificationChannel.EMAIL,
        provider=NotificationProvider.SMTP
        if payload.channel == "smtp"
        else NotificationProvider.GMAIL,
        subject=payload.subject,
        body=payload.body,
        status=NotificationStatus.SENT,
        external_id=receipt.external_id,
        sent_at=now,
    )
    session.add(notification)
    app_row.stage = Stage.INVITED
    app_row.invited_at = now
    await session.commit()
    await session.refresh(notification)
    return NotifyResponse(
        notification_id=notification.id, external_id=receipt.external_id
    )
