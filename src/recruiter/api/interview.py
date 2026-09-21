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
    visible_sheets,
)
from recruiter.pipeline.kit_store import (
    apply_content,
    content_of,
    create_kit,
    job_default_template,
    kit_for,
    snapshot_from_row,
    template_fields,
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


class InterviewKitRead(BaseModel):
    kit: InterviewKit | None
    template_name: str | None = None
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
        )
        for r in rows
    ]


async def _read(session: AsyncSession, app_row: Application, user: User) -> InterviewKitRead:
    row = await kit_for(session, app_row)
    return InterviewKitRead(
        kit=content_of(row) if row else None,
        template_name=row.template_name if row else None,
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
        kit_row = await kit_for(session, app_row)
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
                    raise RuntimeError("No LLM provider configured. Set one up in Settings.")
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
        kit_row = await kit_for(session, app_row)
        if app_row.interview_round != dispatch_round:
            logger.warning(
                "interview kit generation abandoned: round moved from %s to %s "
                "during generation for application %s",
                dispatch_round, app_row.interview_round, application_id,
            )
            return
        rows = await load_assignments(session, application_id)

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
                answered_ids=answered_question_ids(rows_in_round(rows, app_row.interview_round)),
            )
        else:
            kit = build_kit(baseline, texts,
                             criteria_by_probe=criteria_by_probe, now=_now())

        # An interviewer may have submitted their sheet — freezing the
        # round — while the model call was in flight. If so, and there was
        # something to orphan, discard whatever was just computed, success
        # or error, and restore the frozen kit to "ready" instead of
        # overwriting it with a result computed from stale, now-frozen state.
        if is_frozen(rows_in_round(rows, app_row.interview_round)) and existing_questions:
            logger.warning(
                "interview kit regeneration discarded: a sheet was submitted "
                "during generation for application %s", application_id,
            )
            kit = InterviewKit.model_validate(existing_raw).model_copy(
                update={"status": "ready", "error": None}
            )
        if kit_row is None:
            kit_row = await create_kit(session, app_row, round=app_row.interview_round)
        apply_content(kit_row, kit)
        await session.commit()
    await bus.publish({
        "type": "interview_kit", "application_id": application_id, "status": kit.status,
        "job_id": app_row.job_id, "stage_changed": False,
    })


@router.post("/applications/{application_id}/interview-kit/generate", status_code=202)
async def generate_kit(
    application_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    engine: AsyncEngine = Depends(get_engine_dep),
    llm: LLMClient = Depends(get_llm),
    bus: EventBus = Depends(get_event_bus),
) -> dict:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")

    kit_row = await kit_for(session, app_row)
    existing_questions = kit_row.questions if kit_row else []
    frozen = is_frozen(
        rows_in_round(await load_assignments(session, application_id), app_row.interview_round)
    )
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
        kit_row = await create_kit(
            session, app_row, round=app_row.interview_round,
            **template_fields(await job_default_template(session, app_row)),
        )
    kit_row.status = "generating"
    kit_row.error = None
    kit_row.generating_since = _now()
    await session.commit()

    background_tasks.add_task(
        run_generate_kit, application_id=application_id, engine=engine, llm=llm, bus=bus,
    )
    return {"application_id": application_id}


class InterviewKitPatch(BaseModel):
    questions: list[KitQuestion]


@router.patch("/applications/{application_id}/interview-kit",
              response_model=InterviewKitRead)
async def patch_kit(
    application_id: int,
    payload: InterviewKitPatch,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> InterviewKitRead:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    kit_row = await kit_for(session, app_row)
    kit = _require_kit(kit_row)

    ids = [q.id for q in payload.questions]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="duplicate question ids")

    rows = await load_assignments(session, application_id)
    stored_ids = [q.id for q in kit.questions]
    incoming_ids = [q.id for q in payload.questions]

    if not can_edit_questions(user):
        # An assigned interviewer may append, and nothing else.
        if user.id not in {r.user_id for r in rows_in_round(rows, app_row.interview_round)}:
            raise HTTPException(status_code=403, detail="not assigned to this interview")
        prefix = payload.questions[:len(stored_ids)]
        unchanged = [q.model_dump(exclude={"added_by", "answer", "rating"}) for q in prefix] == [
            q.model_dump(exclude={"added_by", "answer", "rating"}) for q in kit.questions
        ]
        if not unchanged:
            raise HTTPException(status_code=403, detail="interviewers may only add questions")

    if is_frozen(rows_in_round(rows, app_row.interview_round)) and any(
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
    # very question the interviewer is struggling with. Also scoped to the
    # CURRENT round, like `is_frozen` above: each round owns its own kit
    # and question ids now, so a question answered in an earlier, closed
    # round cannot lock a same-id question in this one.
    recorded = answered_question_ids(
        r for r in rows_in_round(rows, app_row.interview_round) if r.submitted_at is not None
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


async def _own_assignment(
    session: AsyncSession, app_row: Application, user: User,
) -> InterviewAssignment:
    """The caller's row, or 404. A recruiter/admin with no panel at all gets
    one created on the spot — that is what keeps the single-recruiter flow
    working with zero setup."""
    rows = rows_in_round(
        await load_assignments(session, app_row.id), app_row.interview_round,
    )
    own = next((r for r in rows if r.user_id == user.id), None)
    if own is not None:
        return own
    if not rows and can_edit_questions(user):
        own = InterviewAssignment(
            application_id=app_row.id, user_id=user.id, round=app_row.interview_round,
        )
        session.add(own)
        await session.flush()
        return own
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
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> InterviewKitRead:
    # Row-locked, like submit_sheet: the auto-create in _own_assignment
    # must not run twice for a recruiter's first save arriving concurrently
    # from two tabs, which would otherwise both pass the "no rows yet"
    # check and try to insert the same (application_id, user_id) row.
    app_row = await session.get(Application, application_id, with_for_update=True)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    kit = _require_kit(await kit_for(session, app_row))
    own = await _own_assignment(session, app_row, user)
    if own.submitted_at is not None:
        raise HTTPException(status_code=409, detail="sheet already submitted")
    own.sheet = prune_answers(payload, {q.id for q in kit.questions}).model_dump()
    await session.commit()
    return await _read(session, app_row, user)


@router.post("/applications/{application_id}/interview-kit/sheet/submit",
             response_model=InterviewKitRead)
async def submit_sheet(
    application_id: int,
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
    kit = _require_kit(await kit_for(session, app_row))
    own = await _own_assignment(session, app_row, user)
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
        "job_id": app_row.job_id, "stage_changed": stage_changed,
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

    if not can_edit_questions(user):
        rows = rows_in_round(
            await load_assignments(session, application_id), app_row.interview_round,
        )
        if user.id not in {r.user_id for r in rows}:
            raise HTTPException(status_code=403, detail="not assigned to this interview")

    if llm is None:
        raise HTTPException(
            status_code=503,
            detail="No LLM provider configured — set one in Settings → LLM.",
        )

    job = await session.get(Job, app_row.job_id)
    candidate = await session.get(Candidate, app_row.candidate_id)
    kit_row = await kit_for(session, app_row)
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
