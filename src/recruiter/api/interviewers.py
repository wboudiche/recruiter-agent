"""Who interviews which candidate.

One row per (application, user) in `interview_assignments`; the sheet on
each row is written through `api/interview.py`. Assigning is a recruiter
action; listing is open to every role so an interviewer can see who else
is on the panel.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.candidates import get_event_bus
from recruiter.api.deps import get_session, require_role, require_user
from recruiter.events import EventBus
from recruiter.models import Application, InterviewAssignment, Role, User
from recruiter.pipeline.interview_sheets import close_round_if_complete, sheet_has_content

router = APIRouter(prefix="/api", tags=["interview"], dependencies=[Depends(require_user)])


class InterviewerRead(BaseModel):
    user_id: int
    name: str | None
    email: str
    submitted_at: str | None


class InterviewersPut(BaseModel):
    user_ids: list[int]


async def load_assignments(session: AsyncSession, application_id: int) -> list[InterviewAssignment]:
    return list((await session.execute(
        select(InterviewAssignment)
        .where(InterviewAssignment.application_id == application_id)
        .order_by(InterviewAssignment.created_at, InterviewAssignment.id)
    )).scalars().all())


async def _read_all(session: AsyncSession, application_id: int) -> list[InterviewerRead]:
    rows = await load_assignments(session, application_id)
    users = {u.id: u for u in (await session.execute(
        select(User).where(User.id.in_([r.user_id for r in rows] or [-1]))
    )).scalars().all()}
    return [
        InterviewerRead(
            user_id=r.user_id,
            name=users[r.user_id].name,
            email=users[r.user_id].email,
            submitted_at=r.submitted_at.isoformat() if r.submitted_at else None,
        )
        for r in rows
    ]


@router.get("/applications/{application_id}/interviewers", response_model=list[InterviewerRead])
async def list_interviewers(
    application_id: int, session: AsyncSession = Depends(get_session),
) -> list[InterviewerRead]:
    if await session.get(Application, application_id) is None:
        raise HTTPException(status_code=404, detail="application not found")
    return await _read_all(session, application_id)


@router.put("/applications/{application_id}/interviewers", response_model=list[InterviewerRead])
async def put_interviewers(
    application_id: int,
    payload: InterviewersPut,
    session: AsyncSession = Depends(get_session),
    bus: EventBus = Depends(get_event_bus),
    _: User = Depends(require_role(Role.ADMIN, Role.RECRUITER)),
) -> list[InterviewerRead]:
    """Reconcile to exactly `user_ids`: create missing rows, delete the rest.
    Refuses to delete a submitted sheet, or an unsubmitted one with any
    content — feedback must not vanish by unticking a name."""
    # Row-locked: removing the last unsubmitted interviewer can complete the
    # round (see close_round_if_complete below), same race as submit_sheet.
    app_row = await session.get(Application, application_id, with_for_update=True)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")

    wanted = list(dict.fromkeys(payload.user_ids))  # dedupe, keep order
    existing = await load_assignments(session, application_id)
    by_user = {r.user_id: r for r in existing}
    # Only ids not already on the panel need to be active: an interviewer
    # deactivated after being assigned must not make the panel unsaveable —
    # their existing row is left alone below regardless of is_active.
    to_validate = [uid for uid in wanted if uid not in by_user]
    if to_validate:
        found = {u.id for u in (await session.execute(
            select(User).where(User.id.in_(to_validate), User.is_active.is_(True))
        )).scalars().all()}
        missing = [uid for uid in to_validate if uid not in found]
        if missing:
            raise HTTPException(status_code=422, detail=f"unknown or inactive users: {missing}")

    # sheet_has_content only protects an ACTIVE assignee's draft: once
    # someone is deactivated they can never come back to submit or clear
    # it themselves, so a populated-but-unsubmitted row of theirs must not
    # strand the panel. The submitted-sheet 409 below has no such carve
    # out — a submitted sheet is never removable, active or not.
    to_remove = [row for row in existing if row.user_id not in wanted]
    active_removing: set[int] = set()
    if to_remove:
        active_removing = {u.id for u in (await session.execute(
            select(User).where(
                User.id.in_([r.user_id for r in to_remove]), User.is_active.is_(True),
            )
        )).scalars().all()}

    deleted = False
    for row in existing:
        if row.user_id not in wanted:
            if row.submitted_at is not None:
                raise HTTPException(
                    status_code=409,
                    detail="cannot remove an interviewer whose sheet is submitted",
                )
            if row.user_id in active_removing and sheet_has_content(row.sheet):
                raise HTTPException(
                    status_code=409,
                    detail="cannot remove an interviewer whose sheet has content",
                )
            await session.delete(row)
            deleted = True
    for uid in wanted:
        if uid not in by_user:
            session.add(InterviewAssignment(application_id=application_id, user_id=uid))

    # Removing the last unsubmitted interviewer can leave every remaining
    # assignment submitted, which closes the round the same way a late
    # submit would. Only a removal can do this — a no-op save of the same
    # panel must never re-evaluate whether the round is complete, or a
    # candidate re-entered into SCHEDULED whose round-1 rows are still
    # marked submitted would flip straight back to INTERVIEWED.
    stage_changed = await close_round_if_complete(session, app_row) if deleted else False
    await session.commit()
    # Same event the kit uses, so any open candidate page refetches its
    # interviewer chips and sheets (see lib/sse.ts).
    await bus.publish({
        "type": "interview_kit", "application_id": application_id, "status": "ready",
        "job_id": app_row.job_id, "stage_changed": stage_changed,
    })
    return await _read_all(session, application_id)
