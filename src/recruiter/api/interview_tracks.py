"""Adding and removing a parallel interview (track) in the live round.

Only while the application is SCHEDULED: before that there is no round to
add to, and afterwards a closed round's record must not change. Admins and
recruiters only; registered on `_api_router`, so viewers are also refused
by the viewer guard.
"""
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from recruiter.api.candidates import get_engine_dep, get_event_bus
from recruiter.api.deps import get_session, require_role, require_user
from recruiter.api.interview import InterviewKitRead, _read, dispatch_generation
from recruiter.api.interviewers import load_assignments
from recruiter.api.jobs import get_llm_or_none
from recruiter.api.round_tracks import create_track
from recruiter.events import EventBus
from recruiter.llm.client import LLMClient
from recruiter.models import Application, InterviewTemplate, Role, Stage, User
from recruiter.pipeline.interview_sheets import (
    close_round_if_complete,
    rows_in_track,
    sheet_has_content,
)
from recruiter.pipeline.kit_store import kit_for, kits_in_round, track_key

router = APIRouter(prefix="/api", tags=["interview"], dependencies=[Depends(require_user)])


class TrackCreate(BaseModel):
    template_id: int | None = None


async def _scheduled_app(session: AsyncSession, application_id: int) -> Application:
    # Row-locked like every other track mutation (see submit_sheet).
    app_row = await session.get(Application, application_id, with_for_update=True)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    if app_row.stage != Stage.SCHEDULED:
        raise HTTPException(
            status_code=409, detail="tracks change only while the interview is scheduled",
        )
    return app_row


@router.post("/applications/{application_id}/interview-tracks",
             response_model=InterviewKitRead, status_code=status.HTTP_201_CREATED)
async def add_track(
    application_id: int,
    payload: TrackCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    engine: AsyncEngine = Depends(get_engine_dep),
    llm: LLMClient | None = Depends(get_llm_or_none),
    bus: EventBus = Depends(get_event_bus),
    user: User = Depends(require_role(Role.ADMIN, Role.RECRUITER)),
) -> InterviewKitRead:
    app_row = await _scheduled_app(session, application_id)
    template = None
    if payload.template_id is not None:
        template = await session.get(InterviewTemplate, payload.template_id)
        if template is None or not template.is_active:
            raise HTTPException(status_code=422, detail="unknown or archived interview template")
    key = track_key(payload.template_id)
    if await kit_for(session, app_row, track=key) is not None:
        raise HTTPException(status_code=409, detail="this round already has that track")
    await create_track(session, app_row, template, datetime.now(UTC))
    await session.commit()
    await dispatch_generation(
        session, background_tasks, app_row, [key], engine=engine, llm=llm, bus=bus,
    )
    await bus.publish({
        "type": "interview_kit", "application_id": application_id, "status": "generating",
        "job_id": app_row.job_id, "stage_changed": False, "track": key,
    })
    return await _read(session, app_row, user)


@router.delete("/applications/{application_id}/interview-tracks/{track}",
               response_model=InterviewKitRead)
async def remove_track(
    application_id: int,
    track: str,
    session: AsyncSession = Depends(get_session),
    bus: EventBus = Depends(get_event_bus),
    user: User = Depends(require_role(Role.ADMIN, Role.RECRUITER)),
) -> InterviewKitRead:
    """Remove a track nobody has written in, with its (empty) panel. The
    round's last track stays: a scheduled round needs a kit. Removing a
    track can finish the round — the others all staffed and submitted — so
    completion is re-checked, as a panel removal does."""
    app_row = await _scheduled_app(session, application_id)
    kits = await kits_in_round(session, app_row)
    kit_row = next((k for k in kits if k.track == track), None)
    if kit_row is None:
        raise HTTPException(status_code=404, detail=f"no track {track!r} in this round")
    if len(kits) == 1:
        raise HTTPException(status_code=409, detail="a round keeps at least one track")
    panel = rows_in_track(
        await load_assignments(session, application_id), app_row.interview_round, track,
    )
    if any(r.submitted_at is not None or sheet_has_content(r.sheet) for r in panel):
        raise HTTPException(
            status_code=409, detail="someone on this track has already written feedback",
        )
    for row in panel:
        await session.delete(row)
    await session.delete(kit_row)
    await session.flush()
    stage_changed = await close_round_if_complete(session, app_row)
    await session.commit()
    await bus.publish({
        "type": "interview_kit", "application_id": application_id, "status": "ready",
        "job_id": app_row.job_id, "stage_changed": stage_changed, "track": track,
    })
    return await _read(session, app_row, user)
