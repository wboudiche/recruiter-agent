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
    Refuses to delete a submitted sheet — feedback must not vanish by
    unticking a name."""
    if await session.get(Application, application_id) is None:
        raise HTTPException(status_code=404, detail="application not found")

    wanted = list(dict.fromkeys(payload.user_ids))  # dedupe, keep order
    if wanted:
        found = {u.id for u in (await session.execute(
            select(User).where(User.id.in_(wanted), User.is_active.is_(True))
        )).scalars().all()}
        missing = [uid for uid in wanted if uid not in found]
        if missing:
            raise HTTPException(status_code=422, detail=f"unknown or inactive users: {missing}")

    existing = await load_assignments(session, application_id)
    by_user = {r.user_id: r for r in existing}
    for row in existing:
        if row.user_id not in wanted:
            if row.submitted_at is not None:
                raise HTTPException(
                    status_code=409,
                    detail="cannot remove an interviewer whose sheet is submitted",
                )
            await session.delete(row)
    for uid in wanted:
        if uid not in by_user:
            session.add(InterviewAssignment(application_id=application_id, user_id=uid))
    await session.commit()
    # Same event the kit uses, so any open candidate page refetches its
    # interviewer chips and sheets (see lib/sse.ts).
    await bus.publish({
        "type": "interview_kit", "application_id": application_id, "status": "ready",
    })
    return await _read_all(session, application_id)
