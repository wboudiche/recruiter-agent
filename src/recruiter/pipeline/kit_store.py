"""Reading, creating and converting interview kit rows.

Kept out of the routers so both `api/interview.py` and
`api/applications.py` can use it without importing each other — the same
cycle `interview_sheets.py` already works around.

The Pydantic `InterviewKit` stays the API shape; these two converters are
the only place the row and the schema meet.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.models import Application, InterviewTemplate, Job
from recruiter.models.interview_kit_row import InterviewKitRow
from recruiter.pipeline.interview_kit import snapshot_of
from recruiter.schemas.interview import InterviewKit
from recruiter.schemas.interview_template import TemplateSnapshot

DEFAULT_TRACK = "default"


async def kit_for(
    session: AsyncSession, app_row: Application, *, track: str = DEFAULT_TRACK,
) -> InterviewKitRow | None:
    """The kit for the application's CURRENT round. Reads only — creation is
    explicit at the three points that mean it (entering scheduled, opening
    the next round, and generating on an application that has none yet)."""
    return (await session.execute(
        select(InterviewKitRow).where(
            InterviewKitRow.application_id == app_row.id,
            InterviewKitRow.round == app_row.interview_round,
            InterviewKitRow.track == track,
        )
    )).scalars().one_or_none()


async def create_kit(
    session: AsyncSession,
    app_row: Application,
    *,
    round: int,
    track: str = DEFAULT_TRACK,
    questions: list[dict] | None = None,
    status: str = "ready",
    error: str | None = None,
    template_id: int | None = None,
    template_name: str | None = None,
    template_snapshot: dict | None = None,
) -> InterviewKitRow:
    row = InterviewKitRow(
        application_id=app_row.id, round=round, track=track,
        questions=questions or [], status=status, error=error,
        template_id=template_id, template_name=template_name,
        template_snapshot=template_snapshot,
    )
    session.add(row)
    await session.flush()
    return row


def template_fields(template: InterviewTemplate | None) -> dict:
    """The three kit columns for a template — spread into create_kit, or
    set on an existing row. None yields three Nones: no template."""
    if template is None:
        return {"template_id": None, "template_name": None, "template_snapshot": None}
    return {
        "template_id": template.id,
        "template_name": template.name,
        "template_snapshot": snapshot_of(template).model_dump(),
    }


def snapshot_from_row(row: InterviewKitRow | None) -> TemplateSnapshot | None:
    if row is None or row.template_snapshot is None:
        return None
    return TemplateSnapshot.model_validate(row.template_snapshot)


async def job_default_template(
    session: AsyncSession, app_row: Application,
) -> InterviewTemplate | None:
    """The job's default template, if it has one and it is still active.
    An archived default is treated as no default."""
    job = await session.get(Job, app_row.job_id)
    if job is None or job.default_interview_template_id is None:
        return None
    template = await session.get(InterviewTemplate, job.default_interview_template_id)
    return template if template is not None and template.is_active else None


def content_of(row: InterviewKitRow) -> InterviewKit:
    return InterviewKit.model_validate({
        "status": row.status,
        "error": row.error,
        "generated_at": row.generated_at,
        "generating_since": row.generating_since,
        "submitted_at": row.submitted_at,
        "closed_at": row.closed_at,
        "questions": row.questions or [],
    })


def apply_content(row: InterviewKitRow, kit: InterviewKit) -> None:
    row.status = kit.status
    row.error = kit.error
    row.generated_at = kit.generated_at
    row.generating_since = kit.generating_since
    row.submitted_at = kit.submitted_at
    row.closed_at = kit.closed_at
    row.questions = [q.model_dump() for q in kit.questions]
