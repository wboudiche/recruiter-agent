from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import selectinload

from recruiter.api.candidates import (
    ApplicationCreated,
    get_engine_dep,
    get_event_bus,
    get_llm,
    resume_display_name,
)
from recruiter.api.deps import get_session, require_user
from recruiter.api.interview import run_generate_kit
from recruiter.api.interviewers import load_assignments
from recruiter.api.jobs import get_llm_or_none
from recruiter.config import get_config
from recruiter.events import EventBus
from recruiter.llm.client import LLMClient
from recruiter.models import Application, Candidate, EventLog, InterviewAssignment, Stage
from recruiter.models.interview_assignment import empty_sheet
from recruiter.pipeline.interview_sheets import is_frozen, mark_interviewed, rows_in_round
from recruiter.pipeline.kit_store import create_kit, kit_for
from recruiter.pipeline.orchestrator import (
    process_application,
    re_enrich_application as run_re_enrich,
)
from recruiter.pipeline.router import RoutedInput
from recruiter.schemas.application import ApplicationRead, ApplicationUpdate, ScoreBreakdownItem
from recruiter.schemas.candidate import CandidateRead, CandidateUpdate

# Authorization model: shared workspace. Any user authenticated via OIDC and
# accepted by the domain allowlist (`auth.allowlist`) can read and mutate any
# candidate or application — there is no per-record owner check by design.
# If per-user ownership or role tiers (admin/recruiter/viewer) are ever needed,
# add a column on Candidate/Application and a guard alongside `require_user`.
router = APIRouter(prefix="/api", tags=["applications"], dependencies=[Depends(require_user)])


async def _load_application(
    session: AsyncSession, application_id: int, *, for_update: bool = False,
) -> Application | None:
    """Load an application with the candidate eager-loaded so awaiting_paste
    can be computed without a follow-up query.

    `for_update` row-locks it. Mutating callers need it: reopening a round
    read-modify-writes `interview_round` and then inserts a row per
    panellist at the new round, so two concurrent reopens would both read
    the old round and collide on the assignment unique constraint. The
    other round mutations (submit_sheet, patch_sheet, put_interviewers)
    already lock for the same reason.
    """
    stmt = (
        select(Application)
        .where(Application.id == application_id)
        .options(selectinload(Application.candidate))
    )
    if for_update:
        # Only the applications row; the eager-loaded candidate is a
        # separate SELECT that must not be locked with it.
        stmt = stmt.with_for_update(of=Application)
    return (await session.execute(stmt)).scalar_one_or_none()


@router.get("/applications/{application_id}", response_model=ApplicationRead)
async def get_application(application_id: int, session: AsyncSession = Depends(get_session)) -> ApplicationRead:
    app_row = await _load_application(session, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    errors = await _latest_errors(session, [app_row.id])
    counts = await _sheet_counts(session, [app_row.id])
    return _to_read(app_row, errors.get(app_row.id), counts.get(app_row.id, (0, 0)))


@router.get("/candidates/{candidate_id}", response_model=CandidateRead)
async def get_candidate(
    candidate_id: int, session: AsyncSession = Depends(get_session)
) -> CandidateRead:
    candidate = await session.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return CandidateRead.model_validate(candidate)


@router.get("/candidates/{candidate_id}/resume")
async def get_candidate_resume(
    candidate_id: int, session: AsyncSession = Depends(get_session)
) -> FileResponse:
    candidate = await session.get(Candidate, candidate_id)
    if candidate is None or not candidate.resume_path:
        raise HTTPException(status_code=404, detail="no resume on file for this candidate")

    storage_dir = Path(get_config().resume_storage_path).resolve()
    path = Path(candidate.resume_path).resolve()
    if not path.is_relative_to(storage_dir) or not path.is_file():
        raise HTTPException(status_code=404, detail="resume file missing on disk")

    # "inline" so clicking the link previews the CV in the browser tab instead
    # of forcing a download. Upload only ever accepts .pdf/.docx (415s
    # anything else), so the guessed media type is trustworthy — nosniff
    # still pins it, in case a stored file's actual bytes disagree with its
    # extension, so the browser never reinterprets it as HTML/script.
    return FileResponse(
        path,
        filename=resume_display_name(path.name),
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff"},
    )


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
    if "full_name" in data:
        candidate.full_name = (data["full_name"] or "").strip() or None
    if "email" in data:
        candidate.email = (data["email"] or "").strip() or None
    if "headline" in data:
        candidate.headline = (data["headline"] or "").strip() or None
    if "phone" in data:
        candidate.phone = (data["phone"] or "").strip() or None
    if "location" in data:
        candidate.location = (data["location"] or "").strip() or None
    if "summary" in data:
        candidate.summary = (data["summary"] or "").strip() or None
    await session.commit()
    # `updated_at` carries `onupdate=func.now()`. After commit the
    # in-memory value is stale; without an explicit refresh, Pydantic's
    # lazy attribute read triggers a sync DB hit and crashes with
    # MissingGreenlet in this async context.
    await session.refresh(candidate)
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
    errors = await _latest_errors(session, [r.id for r in rows])
    counts = await _sheet_counts(session, [r.id for r in rows])
    return [_to_read(r, errors.get(r.id), counts.get(r.id, (0, 0))) for r in rows]


# Event types that actually halt the pipeline and are worth surfacing as
# `last_error`. Deliberately NOT a `.endswith(".failed")` suffix match:
# `enrichment.failed` also ends in ".failed" but is non-fatal — the
# orchestrator logs it and then restores the application to SCORED, so
# treating it as a halting error would pin a permanently visible,
# undismissable error onto an otherwise healthy, fully scored card.
_HALTING_FAILURE_EVENT_TYPES = {"extract.failed", "score.failed"}


async def _latest_errors(
    session: AsyncSession, application_ids: list[int]
) -> dict[int, tuple[str, int]]:
    """Map application id → (error message, event id), for those whose
    most recent event is a halting failure (see
    `_HALTING_FAILURE_EVENT_TYPES`).

    The event id travels with the message because consecutive failures
    frequently carry identical text — a recurring rate limit, an expired
    token, a missing model all stringify the same way. A consumer
    watching only the message cannot tell "no new event yet" from "it
    failed again, identically"; the id makes that unambiguous.

    Ordered by `id` rather than `created_at`: two events written in the
    same second tie on the timestamp, and a tie here would flip a card
    between "failed" and "fine" at random.

    One query for the whole batch — `_to_read` runs per row, so a
    per-row lookup would be N+1 across a full board.
    """
    if not application_ids:
        return {}
    newest = (
        select(EventLog.application_id, func.max(EventLog.id).label("max_id"))
        .where(EventLog.application_id.in_(application_ids))
        .group_by(EventLog.application_id)
        .subquery()
    )
    # Only the columns the caller needs — the newest event of every card
    # on the board would otherwise drag its whole payload across the wire.
    rows = (
        await session.execute(
            select(EventLog.id, EventLog.application_id, EventLog.event_type, EventLog.payload)
            .join(newest, EventLog.id == newest.c.max_id)
        )
    ).all()
    out: dict[int, tuple[str, int]] = {}
    for event_id, application_id, event_type, payload in rows:
        if event_type not in _HALTING_FAILURE_EVENT_TYPES:
            continue
        error = (payload or {}).get("error")
        if error:
            out[application_id] = (str(error), event_id)
    return out


async def _sheet_counts(
    session: AsyncSession, application_ids: list[int]
) -> dict[int, tuple[int, int]]:
    """application id → (assigned, submitted) for the LIVE round only.

    Joined to `applications.interview_round` rather than counting every row:
    a reopened two-person panel keeps its round-1 rows submitted forever, so
    counting across rounds makes the board badge read 2/4 — as if half the
    new round were already in — when nothing in it has been submitted.
    """
    if not application_ids:
        return {}
    rows = (await session.execute(
        select(
            InterviewAssignment.application_id,
            func.count(InterviewAssignment.id),
            func.count(InterviewAssignment.submitted_at),
        )
        .join(Application, Application.id == InterviewAssignment.application_id)
        .where(
            InterviewAssignment.application_id.in_(application_ids),
            InterviewAssignment.round == Application.interview_round,
        )
        .group_by(InterviewAssignment.application_id)
    )).all()
    return {app_id: (total, submitted) for app_id, total, submitted in rows}


def _to_read(
    app_row: Application,
    last_error: tuple[str, int] | None = None,
    sheet_counts: tuple[int, int] = (0, 0),
) -> ApplicationRead:
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
        interviewed_at=app_row.interviewed_at,
        offer_at=app_row.offer_at,
        hired_at=app_row.hired_at,
        rejected_at=app_row.rejected_at,
        rejection_reason=app_row.rejection_reason,
        interview_round=app_row.interview_round,
        created_at=app_row.created_at,
        updated_at=app_row.updated_at,
        awaiting_paste=awaiting_paste,
        last_error=last_error[0] if last_error else None,
        last_error_event_id=last_error[1] if last_error else None,
        enrichment=app_row.enrichment,
        sheets_total=sheet_counts[0],
        sheets_submitted=sheet_counts[1],
    )


# Past INVITED, applications advance one stage at a time (interview
# scheduled → held → offer extended → hired), each also allowed to
# fall through to REJECTED instead. HIRED has no entry here: it's fully
# terminal, including to REJECTED (see the explicit check below).
_FORWARD_STAGE_AFTER = {
    Stage.INVITED: Stage.SCHEDULED,
    Stage.SCHEDULED: Stage.INTERVIEWED,
    Stage.INTERVIEWED: Stage.OFFER,
    Stage.OFFER: Stage.HIRED,
}
# Inverse of the above: the one current stage each late stage may be
# entered from. Without this, _FORWARD_STAGE_AFTER only blocks the wrong
# forward step FROM one of its keys — it says nothing about reaching
# SCHEDULED/INTERVIEWED/OFFER/HIRED from a current stage that isn't a key
# at all (e.g. VALIDATED → SCHEDULED, or REJECTED → HIRED), which would
# otherwise sail through unguarded.
_REQUIRED_PREDECESSOR = {target: source for source, target in _FORWARD_STAGE_AFTER.items()}


def _validate_transition(current: Stage, target: Stage) -> None:
    """Enforce business rules. Raises HTTPException(409) on illegal transitions."""
    if current == Stage.HIRED:
        raise HTTPException(status_code=409, detail="cannot move from hired")
    # Reopening for another interview round. Without this, a second
    # interview could only be reached by rejecting the candidate and
    # re-inviting them, since SCHEDULED is otherwise entered from INVITED
    # alone — see the interview-rounds migration.
    if (current, target) == (Stage.INTERVIEWED, Stage.SCHEDULED):
        return
    if current in _FORWARD_STAGE_AFTER and target != Stage.REJECTED:
        expected = _FORWARD_STAGE_AFTER[current]
        if target != expected:
            raise HTTPException(
                status_code=409,
                detail=f"cannot move from {current.value} to {target.value}; "
                f"expected {expected.value} or rejected",
            )
    if target in _REQUIRED_PREDECESSOR and current != _REQUIRED_PREDECESSOR[target]:
        raise HTTPException(
            status_code=409,
            detail=f"cannot move to {target.value} from {current.value}; "
            f"expected {_REQUIRED_PREDECESSOR[target].value}",
        )
    # Moving to SCORED is allowed from VALIDATED (unvalidate) and from
    # REJECTED (unreject). Other source stages don't have a meaningful
    # "back to scored" semantic and are blocked.
    if target == Stage.SCORED and current not in {Stage.VALIDATED, Stage.REJECTED}:
        raise HTTPException(
            status_code=409,
            detail=f"cannot move from {current.value} to scored",
        )
    if target == Stage.VALIDATED and current != Stage.SCORED:
        raise HTTPException(
            status_code=409,
            detail=f"cannot validate from stage {current.value}",
        )
    if target == Stage.REJECTED and current == Stage.REJECTED:
        raise HTTPException(status_code=409, detail="already rejected")


async def _open_next_round(session: AsyncSession, app_row: Application) -> None:
    """Reopen an interviewed application for another interview round.

    The round that just closed is left exactly as it is — its sheets stay
    submitted and immutable, the record of that conversation — and a fresh
    set of rows is created for the same panel with empty sheets, so the
    recruiter only touches the panel when round two is a different one.

    The new round's kit starts as a copy of the closed round's questions
    rather than a fresh generation: the closed round's answers are keyed
    to its question ids, and `is_frozen` (scoped to that round) still
    protects them. The new round's own kit is untouched and free to
    regenerate.
    """
    previous_round = app_row.interview_round
    panel = rows_in_round(await load_assignments(session, app_row.id), previous_round)
    previous_kit = await kit_for(session, app_row)  # still the old round here

    app_row.interview_round = previous_round + 1
    # The round is open again, so the application is no longer interviewed.
    app_row.interviewed_at = None
    for row in panel:
        session.add(InterviewAssignment(
            application_id=app_row.id,
            user_id=row.user_id,
            round=app_row.interview_round,
            sheet=empty_sheet(),
        ))
    if previous_kit is not None:
        # Carry the previous kit's status and error forward rather than
        # forcing "ready": a round stuck in "error" must stay visibly
        # broken on reopen too, or the recruiter sees an empty ready kit
        # with the failure hidden instead of a reason to regenerate it.
        await create_kit(
            session, app_row,
            round=app_row.interview_round,
            questions=list(previous_kit.questions or []),
            status=previous_kit.status,
            error=previous_kit.error,
        )


@router.patch("/applications/{application_id}", response_model=ApplicationRead)
async def patch_application(
    application_id: int,
    payload: ApplicationUpdate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    engine: AsyncEngine = Depends(get_engine_dep),
    # get_llm_or_none, not get_llm: most stage moves have nothing to do
    # with the LLM, and Depends(...) is resolved eagerly for every request
    # regardless of which branch below actually runs — a bare
    # Depends(get_llm) would 503 every PATCH (even 404s) whenever the LLM
    # provider isn't configured. See its docstring in jobs.py.
    llm: LLMClient | None = Depends(get_llm_or_none),
    bus: EventBus = Depends(get_event_bus),
) -> ApplicationRead:
    app_row = await _load_application(session, application_id, for_update=True)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")

    if payload.notes is not None:
        app_row.notes = payload.notes

    schedule_kit_generation = False
    if payload.stage is not None:
        new_stage = Stage(payload.stage)
        previous_stage = app_row.stage
        _validate_transition(app_row.stage, new_stage)
        app_row.stage = new_stage
        now = datetime.now(timezone.utc)
        if new_stage == Stage.VALIDATED:
            app_row.validated_at = now
        elif new_stage == Stage.SCHEDULED and previous_stage == Stage.INTERVIEWED:
            app_row.scheduled_at = now
            await _open_next_round(session, app_row)
        elif new_stage == Stage.SCHEDULED:
            app_row.scheduled_at = now
            # If a sheet in THIS round was already submitted, the question
            # list is frozen — see pipeline/interview_sheets.is_frozen.
            # Regenerating would mint fresh question ids and orphan that
            # submitted sheet's answers. But that's only a real risk when
            # there's something to orphan: frozen with an empty question
            # list (nothing was ever asked) is safe to generate into
            # exactly as if it weren't frozen at all.
            kit_row = await kit_for(session, app_row)
            existing_questions = kit_row.questions if kit_row else []
            frozen = is_frozen(rows_in_round(
                await load_assignments(session, app_row.id), app_row.interview_round,
            ))
            if frozen and existing_questions:
                if kit_row.status != "ready":
                    # A prior freeze-in-flight (see run_generate_kit) or a
                    # since-deleted LLM provider can leave the kit stuck in
                    # "error"/"generating" with no way to ever regenerate
                    # again. Recover it to "ready" with its questions
                    # intact rather than leave it stuck forever.
                    kit_row.status = "ready"
                    kit_row.error = None
                # else: already "ready" — leave the kit exactly as it is.
            else:
                # Mark the kit pending here, but enqueue the model call for
                # AFTER the commit below. The transition must be durable
                # before anything that can fail runs — a stuck stage is far
                # worse than a missing kit. Preserve any existing questions
                # (e.g. a candidate moved back to SCHEDULED after an
                # interview must not lose recorded answers/ratings) —
                # mirrors generate_kit's logic.
                if kit_row is None:
                    kit_row = await create_kit(session, app_row, round=app_row.interview_round)
                kit_row.status = "generating"
                kit_row.error = None
                # Pairs with generate_kit's idempotency check, so a
                # manual Generate during this run is a no-op rather
                # than a second model call.
                kit_row.generating_since = now.isoformat()
                schedule_kit_generation = True
        elif new_stage == Stage.INTERVIEWED:
            # The recruiter closed the round by hand (a no-show, say).
            # Shares mark_interviewed with the all-sheets-in path in
            # submit_sheet so both stamp interviewed_at/closed_at the same
            # way. With no kit yet, there's nothing to stamp closed.
            kit_row = await kit_for(session, app_row)
            if kit_row is not None:
                mark_interviewed(app_row, kit_row, now)
            else:
                app_row.interviewed_at = now
        elif new_stage == Stage.OFFER:
            app_row.offer_at = now
        elif new_stage == Stage.HIRED:
            app_row.hired_at = now
        elif new_stage == Stage.REJECTED:
            app_row.rejected_at = now
        elif new_stage == Stage.SCORED:
            app_row.validated_at = None
            # Moving back out of rejected → drop the stale reason so
            # the UI doesn't keep showing it on a now-active candidate.
            app_row.rejection_reason = None
            app_row.rejected_at = None

    # rejection_reason is captured by the Reject dialog and persisted
    # alongside the stage transition. Empty string explicitly clears
    # the value; None leaves whatever's there alone.
    if payload.rejection_reason is not None:
        app_row.rejection_reason = payload.rejection_reason or None

    await session.commit()
    await session.refresh(app_row)
    # Ensure candidate is loaded for awaiting_paste computation.
    await session.refresh(app_row, attribute_names=["candidate"])

    if schedule_kit_generation:
        if llm is not None:
            background_tasks.add_task(
                run_generate_kit,
                application_id=application_id, engine=engine, llm=llm, bus=bus,
            )
        else:
            # No LLM configured: nothing to enqueue. The stage transition
            # above is already committed and safe either way; leave the
            # kit in an error state rather than stuck at "generating"
            # forever with no task ever running to resolve it.
            kit_row = await kit_for(session, app_row)
            if kit_row is not None:
                kit_row.status = "error"
                kit_row.error = "No LLM provider configured. Set one up in Settings."
            await session.commit()
            await session.refresh(app_row)
    counts = await _sheet_counts(session, [app_row.id])
    return _to_read(app_row, sheet_counts=counts.get(app_row.id, (0, 0)))



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

    # Clear the cached bundle and flip stage to ENRICHING synchronously
    # so the UI can show the loader immediately. The orchestrator's
    # re-enrich entry point will fetch fresh signals and restore the
    # stage to SCORED. We do NOT re-run extract/score — that's a
    # separate concern (the user can Reject + re-add for a full rerun).
    app_row.enrichment = None
    app_row.stage = Stage.ENRICHING
    await session.commit()

    background_tasks.add_task(
        run_re_enrich,
        application_id=application_id,
        engine=engine,
        llm=llm,
        bus=bus,
    )
    return ApplicationCreated(application_id=application_id)
