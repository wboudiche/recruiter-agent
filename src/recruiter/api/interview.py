"""Interview kit endpoints.

Generation runs in a background task deliberately: the stage transition that
triggers it must be durable before any model is called, so a failed
generation can never leave a candidate stuck between stages.
"""
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from recruiter.api.candidates import get_engine_dep, get_event_bus, get_llm
from recruiter.api.deps import get_session, require_user
from recruiter.api.interviewers import load_assignments
from recruiter.api.jobs import get_llm_or_none
from recruiter.api.kit_tracks import adopt_orphan_rows, kit_for_caller, own_row, resolve_track
from recruiter.events import EventBus
from recruiter.llm.client import LLMClient
from recruiter.models import Application, Candidate, InterviewAssignment, InterviewKitRow, Job, User
from recruiter.pipeline.candidate_profile import profile_text
from recruiter.pipeline.interview_kit import (
    build_kit,
    fixed_questions,
    generation_in_flight,
    merge_regenerated,
    wants_probes,
)
from recruiter.pipeline.interview_kit_generator import draft_question, generate_probes
from recruiter.pipeline.interview_sheets import (
    answered_question_ids,
    can_edit_questions,
    close_round_if_complete,
    is_frozen,
    prune_answers,
    rows_in_round,
    rows_in_track,
    visible_kits,
    visible_sheets,
)
from recruiter.pipeline.kit_store import (
    DEFAULT_TRACK,
    apply_content,
    content_of,
    create_kit,
    job_default_template,
    kit_for,
    kits_in_round,
    snapshot_from_row,
    template_fields,
    track_key,
)
from recruiter.schemas.interview import (
    BaselineQuestion,
    GeneratedQuestion,
    InterviewKit,
    InterviewSheet,
    KitQuestion,
    SheetRead,
)
from recruiter.schemas.job import CriteriaItem

router = APIRouter(prefix="/api", tags=["interview"], dependencies=[Depends(require_user)])
logger = logging.getLogger(__name__)

# Shown on a kit that needs generated probes when no model is configured.
NO_LLM_PROVIDER = "No LLM provider configured. Set one up in Settings."


class TrackRead(BaseModel):
    track: str
    template_id: int | None = None
    template_name: str | None = None
    kit: InterviewKit


class InterviewKitRead(BaseModel):
    # Kept for one-track clients: the caller's own track if they are on one,
    # otherwise the round's first track. New clients read `tracks`.
    kit: InterviewKit | None
    template_name: str | None = None
    # Every track of the live round the caller may see, in creation order —
    # see pipeline/interview_sheets.visible_kits.
    tracks: list[TrackRead] = Field(default_factory=list)
    # Filtered per caller — see pipeline/interview_sheets.visible_sheets.
    sheets: list[SheetRead] = Field(default_factory=list)


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def _sheets_for(
    session: AsyncSession, app_row: Application, user: User,
) -> list[SheetRead]:
    rows = visible_sheets(
        await load_assignments(session, app_row.id),
        user=user, current_round=app_row.interview_round,
    )
    if not rows:
        return []
    users = {u.id: u for u in (await session.execute(
        select(User).where(User.id.in_([r.user_id for r in rows]))
    )).scalars().all()}
    return [
        SheetRead(
            user_id=r.user_id, name=users[r.user_id].name, email=users[r.user_id].email,
            sheet=InterviewSheet.model_validate(r.sheet or {}),
            submitted_at=r.submitted_at.isoformat() if r.submitted_at else None,
            round=r.round,
            track=r.track,
        )
        for r in rows
    ]


async def _read(session: AsyncSession, app_row: Application, user: User) -> InterviewKitRead:
    rows = await load_assignments(session, app_row.id)
    shown = visible_kits(
        await kits_in_round(session, app_row), rows,
        user=user, current_round=app_row.interview_round,
    )
    own = own_row(rows_in_round(rows, app_row.interview_round), user)
    primary = next((k for k in shown if own is not None and k.track == own.track), None)
    if primary is None and shown:
        primary = shown[0]
    return InterviewKitRead(
        kit=content_of(primary) if primary else None,
        template_name=primary.template_name if primary else None,
        tracks=[
            TrackRead(track=k.track, template_id=k.template_id,
                      template_name=k.template_name, kit=content_of(k))
            for k in shown
        ],
        sheets=await _sheets_for(session, app_row, user),
    )


@router.get("/applications/{application_id}/interview-kit", response_model=InterviewKitRead)
async def get_kit(
    application_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> InterviewKitRead:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    return await _read(session, app_row, user)


async def run_generate_kit(
    *, application_id: int, engine: AsyncEngine, llm: LLMClient | None, bus: EventBus,
    track: str = DEFAULT_TRACK,
) -> None:
    """Generate probes and store the assembled kit. Never raises."""
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        app_row = await session.get(Application, application_id)
        if app_row is None:
            return
        # Captured before the model call so it reflects the kit as it was
        # when generation was dispatched — used both to build an error kit
        # that keeps its questions (below) and, after the model call, to
        # detect whether there was anything a late freeze could orphan.
        # `dispatch_round` does the same job for a round BUMP: SCHEDULED →
        # INTERVIEWED → SCHEDULED is a legal one-click round trip, and
        # `kit_row` above is only correct for the round as it stood here.
        kit_row = await kit_for(session, app_row, track=track)
        dispatch_round = app_row.interview_round
        existing_raw = content_of(kit_row).model_dump() if kit_row else {}
        existing_questions = existing_raw.get("questions") or []
        # The model call is the only thing inside the try: assembling the
        # kit is deferred until after the lock below, so it can be built
        # from a panel snapshot that is not already stale.
        baseline: list[BaselineQuestion] = []
        texts: list[str] = []
        criteria_by_probe: list[str | None] = []
        failure: str | None = None
        try:
            # Built from what the kit was created with, never the live
            # template: editing a template must not rewrite a round
            # already under way. Parsed inside the try so a malformed
            # stored snapshot becomes an error kit rather than an
            # exception escaping this "never raises" background task.
            snapshot = snapshot_from_row(kit_row)
            job = await session.get(Job, app_row.job_id)
            candidate = await session.get(Candidate, app_row.candidate_id)
            job_baseline = [BaselineQuestion.model_validate(b)
                            for b in (job.interview_baseline or [])]
            baseline = fixed_questions(snapshot, job_baseline)
            if wants_probes(snapshot):
                if llm is None:
                    # patch_application only dispatches without a model
                    # when the snapshot wants no probes; recorded as an
                    # error kit by the except below if that ever changes.
                    raise RuntimeError(NO_LLM_PROVIDER)
                generated = await generate_probes(
                    profile=profile_text(candidate, enrichment=app_row.enrichment),
                    criteria=[CriteriaItem.model_validate(c) for c in (job.criteria or [])],
                    score_breakdown=app_row.score_breakdown,
                    baseline=baseline,
                    llm=llm,
                )
                texts = [q.text for q in generated.questions]
                criteria_by_probe = [q.criterion for q in generated.questions]
        except Exception as exc:  # noqa: BLE001 — recorded, not swallowed
            logger.warning("interview kit generation failed: %s", exc, exc_info=True)
            failure = str(exc)[:500]

        # Read the panel ONCE, under the row lock, after the model call —
        # both things that can change across an LLM round trip are then
        # decided from the same snapshot. `is_frozen` covers a sheet
        # SUBMITTED meanwhile; `answered_question_ids` covers answers TYPED
        # meanwhile, which the freeze does not, because it only begins at
        # the first submit.
        await session.refresh(app_row, with_for_update=True)
        # The round can move while the model call above is in flight — see
        # `dispatch_round` above. `kit_row` was resolved for the round as
        # it stood at dispatch; if the round has since moved, that row now
        # belongs to a DIFFERENT round — possibly closed history — and
        # writing to it would silently reopen and rewrite it. The freeze
        # guard below only inspects the CURRENT round's rows, which are
        # empty right after a reopen, so it cannot catch this on its own.
        # Re-resolve against the current round and abandon the write
        # entirely if it moved, rather than create or overwrite anything.
        kit_row = await kit_for(session, app_row, track=track)
        if app_row.interview_round != dispatch_round:
            logger.warning(
                "interview kit generation abandoned: round moved from %s to %s "
                "during generation for application %s",
                dispatch_round, app_row.interview_round, application_id,
            )
            return
        if kit_row is None:
            # The track was removed while the model was running (see
            # api/interview_tracks.remove_track). Recreating it here would
            # resurrect a track the recruiter just deleted.
            logger.warning(
                "interview kit generation abandoned: track %s was removed during "
                "generation for application %s", track, application_id,
            )
            return
        track_rows = rows_in_track(
            await load_assignments(session, application_id), app_row.interview_round, track,
        )

        if failure is not None:
            # Keep whatever questions the existing kit had rather than wipe
            # them: a failed regeneration must not erase recorded
            # answers/ratings just because the model call blew up.
            kit = (
                InterviewKit.model_validate(existing_raw).model_copy(
                    update={"status": "error", "error": failure}
                )
                if existing_questions
                else InterviewKit(status="error", error=failure)
            )
        elif existing_questions:
            kit = merge_regenerated(
                InterviewKit.model_validate(existing_raw), baseline, texts,
                criteria_by_probe=criteria_by_probe, now=_now(),
                answered_ids=answered_question_ids(track_rows),
            )
        else:
            kit = build_kit(baseline, texts,
                             criteria_by_probe=criteria_by_probe, now=_now())

        # An interviewer may have submitted their sheet — freezing the
        # round — while the model call was in flight. If so, and there was
        # something to orphan, discard whatever was just computed, success
        # or error, and restore the frozen kit to "ready" instead of
        # overwriting it with a result computed from stale, now-frozen state.
        if is_frozen(track_rows) and existing_questions:
            logger.warning(
                "interview kit regeneration discarded: a sheet was submitted "
                "during generation for application %s", application_id,
            )
            kit = InterviewKit.model_validate(existing_raw).model_copy(
                update={"status": "ready", "error": None}
            )
        apply_content(kit_row, kit)
        await session.commit()
    await bus.publish({
        "type": "interview_kit", "application_id": application_id, "status": kit.status,
        "job_id": app_row.job_id, "stage_changed": False, "track": track,
    })


async def dispatch_generation(
    session: AsyncSession, background_tasks: BackgroundTasks, app_row: Application,
    tracks: list[str], *, engine: AsyncEngine, llm: LLMClient | None, bus: EventBus,
) -> None:
    """Enqueue one generation per track, after the commit that marked each
    track's kit `generating` — the stage transition must be durable before
    anything that can fail runs.

    A track whose snapshot wants no probes runs without a model. One that
    needs a model when none is configured is failed on its own — the other
    tracks still generate — rather than left stuck at `generating` with no
    task ever coming to resolve it.
    """
    failed = False
    for track in tracks:
        kit_row = await kit_for(session, app_row, track=track)
        if kit_row is None:
            continue
        if llm is not None or not wants_probes(snapshot_from_row(kit_row)):
            background_tasks.add_task(
                run_generate_kit, application_id=app_row.id, track=track,
                engine=engine, llm=llm, bus=bus,
            )
        else:
            kit_row.status = "error"
            kit_row.error = NO_LLM_PROVIDER
            failed = True
    if failed:
        await session.commit()


@router.post("/applications/{application_id}/interview-kit/generate", status_code=202)
async def generate_kit(
    application_id: int,
    background_tasks: BackgroundTasks,
    track: str | None = None,
    session: AsyncSession = Depends(get_session),
    engine: AsyncEngine = Depends(get_engine_dep),
    llm: LLMClient = Depends(get_llm),
    bus: EventBus = Depends(get_event_bus),
) -> dict:
    # Row-locked like every other track mutation: this endpoint can now
    # create a track and rewrite panel rows (adopt_orphan_rows below), not
    # merely flip a status. It also closes the race between two concurrent
    # first-Generate calls, which the unique (application, round, track)
    # key would otherwise turn into a 500 instead of the idempotent no-op
    # `generation_in_flight` intends.
    app_row = await session.get(Application, application_id, with_for_update=True)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")

    kits = await kits_in_round(session, app_row)
    if kits:
        kit_row = resolve_track(kits, track)
    elif track is not None:
        raise HTTPException(status_code=404, detail=f"no track {track!r} in this round")
    else:
        kit_row = None
    existing_questions = kit_row.questions if kit_row else []
    frozen = kit_row is not None and is_frozen(rows_in_track(
        await load_assignments(session, application_id), app_row.interview_round,
        kit_row.track,
    ))
    # A freeze only blocks regeneration when there is something it could
    # orphan. Frozen with an empty question list means nothing has ever
    # been asked yet, so generation may proceed exactly as if it weren't
    # frozen at all.
    if frozen and existing_questions:
        if kit_row.status != "ready":
            # Nothing left to regenerate into — recover the kit that's
            # stuck in "error"/"generating" straight to "ready" with its
            # questions intact instead of leaving it stuck forever with no
            # path back (regeneration can never run again once frozen).
            kit_row.status = "ready"
            kit_row.error = None
            await session.commit()
            return {"application_id": application_id}
        raise HTTPException(
            status_code=409, detail="questions are frozen: a sheet has been submitted",
        )

    # Idempotent: a double-click or a second tab would otherwise buy a second
    # LLM call whose result just overwrites the first.
    existing_for_flight = (
        {"status": kit_row.status, "generating_since": kit_row.generating_since}
        if kit_row else None
    )
    if generation_in_flight(existing_for_flight, now=datetime.now(UTC)):
        return {"application_id": application_id}

    if kit_row is None:
        template = await job_default_template(session, app_row)
        kit_row = await create_kit(
            session, app_row, round=app_row.interview_round,
            track=track_key(template.id if template else None),
            **template_fields(template),
        )
        adopt_orphan_rows(
            [kit_row],
            rows_in_round(await load_assignments(session, application_id),
                          app_row.interview_round),
        )
    kit_row.status = "generating"
    kit_row.error = None
    kit_row.generating_since = _now()
    await session.commit()

    background_tasks.add_task(
        run_generate_kit, application_id=application_id, engine=engine, llm=llm, bus=bus,
        track=kit_row.track,
    )
    return {"application_id": application_id}


class InterviewKitPatch(BaseModel):
    questions: list[KitQuestion]


@router.patch("/applications/{application_id}/interview-kit",
              response_model=InterviewKitRead)
async def patch_kit(
    application_id: int,
    payload: InterviewKitPatch,
    track: str | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> InterviewKitRead:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")

    kits = await kits_in_round(session, app_row)
    if not kits:
        raise HTTPException(status_code=404, detail="no interview kit; generate one first")

    ids = [q.id for q in payload.questions]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="duplicate question ids")

    rows = rows_in_round(await load_assignments(session, application_id), app_row.interview_round)
    kit_row = kit_for_caller(kits, rows, user, track)
    kit = content_of(kit_row)
    # Freeze and recorded answers are this track's alone: a submitted RH
    # sheet must not lock the technical questions.
    track_rows = [r for r in rows if r.track == kit_row.track]
    stored_ids = [q.id for q in kit.questions]
    incoming_ids = [q.id for q in payload.questions]

    if not can_edit_questions(user):
        # An assigned interviewer may append to their own track, and
        # nothing else.
        prefix = payload.questions[:len(stored_ids)]
        unchanged = [q.model_dump(exclude={"added_by", "answer", "rating"}) for q in prefix] == [
            q.model_dump(exclude={"added_by", "answer", "rating"}) for q in kit.questions
        ]
        if not unchanged:
            raise HTTPException(status_code=403, detail="interviewers may only add questions")

    if is_frozen(track_rows) and any(
        qid not in incoming_ids for qid in stored_ids
    ):
        raise HTTPException(
            status_code=409, detail="questions are frozen: a sheet has been submitted",
        )

    # A submitted answer is a record of what was asked and what was said;
    # rewording the question afterwards changes what that record means,
    # which matters the moment a hiring decision is questioned. Scoped to
    # questions someone actually answered or rated in a SUBMITTED sheet, so
    # an untouched question stays editable and the "fix a typo after one
    # interview" case the design protected still works. A draft answer locks
    # nothing: there is no record yet, and the recruiter may be fixing the
    # very question the interviewer is struggling with. Also scoped to this
    # track of the CURRENT round, like `is_frozen` above: each track owns
    # its own kit and question ids, so an answer on another track, or in an
    # earlier round, cannot lock a same-id question here.
    recorded = answered_question_ids(
        r for r in track_rows if r.submitted_at is not None
    )
    stored_text = {q.id: q.text for q in kit.questions}
    reworded = [
        q.id for q in payload.questions
        if q.id in recorded and q.id in stored_text and q.text != stored_text[q.id]
    ]
    if reworded:
        raise HTTPException(
            status_code=409,
            detail="cannot reword a question that has been answered in a submitted sheet: "
            + ", ".join(reworded),
        )

    # Legacy per-question answer/rating are read-only: carry over whatever
    # the stored kit has and never take them from the client. `added_by`
    # is server-assigned on append and preserved otherwise.
    legacy = {q.id: q for q in kit.questions}
    kit.questions = [
        q.model_copy(update={
            "answer": legacy[q.id].answer if q.id in legacy else None,
            "rating": legacy[q.id].rating if q.id in legacy else None,
            "added_by": legacy[q.id].added_by if q.id in legacy
                        else (None if can_edit_questions(user) else user.id),
        })
        for q in payload.questions
    ]
    apply_content(kit_row, kit)
    await session.commit()
    return await _read(session, app_row, user)


async def _sheet_target(
    session: AsyncSession, app_row: Application, user: User, requested: str | None,
) -> tuple[InterviewKit, InterviewAssignment]:
    """The kit a sheet save or submit belongs to, and the caller's row.

    The caller's own assignment names the track; `?track=` may only repeat
    it (409 otherwise — their sheet is on another track). A recruiter or
    admin with no row gets one created on a track whose panel is empty —
    phase 1's zero-setup single-recruiter flow — naming the track with
    `?track=` when the round has several."""
    kits = await kits_in_round(session, app_row)
    rows = rows_in_round(
        await load_assignments(session, app_row.id), app_row.interview_round,
    )
    own = own_row(rows, user)
    if own is not None:
        if requested is not None and requested != own.track:
            raise HTTPException(status_code=409, detail="your sheet is on another track")
        return _require_kit(next((k for k in kits if k.track == own.track), None)), own
    kit_row = resolve_track(kits, requested)
    if can_edit_questions(user) and not any(r.track == kit_row.track for r in rows):
        own = InterviewAssignment(
            application_id=app_row.id, user_id=user.id,
            round=app_row.interview_round, track=kit_row.track,
        )
        session.add(own)
        await session.flush()
        return content_of(kit_row), own
    raise HTTPException(status_code=404, detail="you are not assigned to this interview")


def _require_kit(kit_row: InterviewKitRow | None) -> InterviewKit:
    if kit_row is None:
        raise HTTPException(status_code=404, detail="no interview kit; generate one first")
    return content_of(kit_row)


@router.patch("/applications/{application_id}/interview-kit/sheet",
              response_model=InterviewKitRead)
async def patch_sheet(
    application_id: int,
    payload: InterviewSheet,
    track: str | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> InterviewKitRead:
    # Row-locked, like submit_sheet: the auto-create in _sheet_target
    # must not run twice for a recruiter's first save arriving concurrently
    # from two tabs, which would otherwise both pass the "no rows yet"
    # check and try to insert the same (application_id, user_id) row.
    app_row = await session.get(Application, application_id, with_for_update=True)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    kit, own = await _sheet_target(session, app_row, user, track)
    if own.submitted_at is not None:
        raise HTTPException(status_code=409, detail="sheet already submitted")
    own.sheet = prune_answers(payload, {q.id for q in kit.questions}).model_dump()
    await session.commit()
    return await _read(session, app_row, user)


@router.post("/applications/{application_id}/interview-kit/sheet/submit",
             response_model=InterviewKitRead)
async def submit_sheet(
    application_id: int,
    track: str | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    bus: EventBus = Depends(get_event_bus),
) -> InterviewKitRead:
    # Row-locked: two interviewers submitting their last two sheets at
    # nearly the same instant would otherwise both read all_submitted() as
    # True under READ COMMITTED and both close the round. The lock queues
    # the second submit behind the first's commit.
    app_row = await session.get(Application, application_id, with_for_update=True)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    kit, own = await _sheet_target(session, app_row, user, track)
    if own.submitted_at is not None:
        raise HTTPException(status_code=409, detail="sheet already submitted")
    own.submitted_at = datetime.now(UTC)
    await session.flush()

    # Advance only from SCHEDULED, and only once every sheet is in. Already
    # interviewed or beyond means this is a late sheet on a closed round.
    stage_changed = await close_round_if_complete(session, app_row)
    await session.commit()
    await bus.publish({
        "type": "interview_kit", "application_id": application_id, "status": kit.status,
        "job_id": app_row.job_id, "stage_changed": stage_changed, "track": own.track,
    })
    return await _read(session, app_row, user)


class DraftQuestionRequest(BaseModel):
    """`hint` is what the recruiter wants probed; empty means "anything missing"."""

    hint: str | None = Field(default=None, max_length=2000)


class DraftQuestionResponse(BaseModel):
    question: GeneratedQuestion


@router.post(
    "/applications/{application_id}/interview-kit/draft-question",
    response_model=DraftQuestionResponse,
)
async def draft_kit_question(
    application_id: int,
    payload: DraftQuestionRequest,
    track: str | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    # get_llm_or_none, not get_llm: FastAPI resolves dependencies eagerly, so
    # Depends(get_llm) would 503 before this handler could 404 an unknown
    # application. Validate the request first, then require the model.
    llm: LLMClient | None = Depends(get_llm_or_none),
) -> DraftQuestionResponse:
    """Draft ONE extra question and hand it back unsaved.

    Synchronous, unlike whole-kit generation: the recruiter clicked and is
    waiting, and nothing here can strand a stage transition, so a background
    task would only add latency and a polling problem.

    Nothing is persisted. The draft goes back to the panel as an ordinary
    editable row, so it is read — and can be reworded — before it ever
    becomes part of the interview record.
    """
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")

    rows = rows_in_round(
        await load_assignments(session, application_id), app_row.interview_round,
    )
    if not can_edit_questions(user) and own_row(rows, user) is None:
        raise HTTPException(status_code=403, detail="not assigned to this interview")

    if llm is None:
        raise HTTPException(
            status_code=503,
            detail="No LLM provider configured — set one in Settings → LLM.",
        )

    job = await session.get(Job, app_row.job_id)
    candidate = await session.get(Candidate, app_row.candidate_id)
    kits = await kits_in_round(session, app_row)
    kit_row = kit_for_caller(kits, rows, user, track) if kits else None
    existing = [
        q.get("text", "")
        for q in (kit_row.questions if kit_row else [])
        if q.get("text")
    ]
    try:
        question = await draft_question(
            profile=profile_text(candidate, enrichment=app_row.enrichment),
            criteria=[CriteriaItem.model_validate(c) for c in (job.criteria or [])],
            score_breakdown=app_row.score_breakdown,
            existing_questions=existing,
            hint=payload.hint,
            llm=llm,
        )
    except Exception as exc:  # noqa: BLE001 — surfaced to the caller, not swallowed
        logger.warning("interview question draft failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Could not draft a question: {exc}") from exc
    return DraftQuestionResponse(question=question)
