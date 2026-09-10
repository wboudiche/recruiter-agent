"""Interview kit endpoints.

Generation runs in a background task deliberately: the stage transition that
triggers it must be durable before any model is called, so a failed
generation can never leave a candidate stuck between stages.
"""
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from recruiter.api.candidates import get_engine_dep, get_event_bus, get_llm
from recruiter.api.deps import get_session, require_user
from recruiter.events import EventBus
from recruiter.llm.client import LLMClient
from recruiter.models import Application, Candidate, Job, Stage
from recruiter.pipeline.interview_kit import build_kit, merge_regenerated
from recruiter.pipeline.interview_kit_generator import generate_probes
from recruiter.schemas.interview import (
    BaselineQuestion,
    InterviewKit,
    KitQuestion,
)
from recruiter.schemas.job import CriteriaItem

router = APIRouter(prefix="/api", tags=["interview"], dependencies=[Depends(require_user)])
logger = logging.getLogger(__name__)


class InterviewKitRead(BaseModel):
    kit: InterviewKit | None


def _now() -> str:
    return datetime.now(UTC).isoformat()


@router.get("/applications/{application_id}/interview-kit", response_model=InterviewKitRead)
async def get_kit(
    application_id: int,
    session: AsyncSession = Depends(get_session),
) -> InterviewKitRead:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    raw = app_row.interview_kit
    return InterviewKitRead(kit=InterviewKit.model_validate(raw) if raw else None)


async def run_generate_kit(
    *, application_id: int, engine: AsyncEngine, llm: LLMClient, bus: EventBus,
) -> None:
    """Generate probes and store the assembled kit. Never raises."""
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        app_row = await session.get(Application, application_id)
        if app_row is None:
            return
        job = await session.get(Job, app_row.job_id)
        candidate = await session.get(Candidate, app_row.candidate_id)
        baseline = [BaselineQuestion.model_validate(b)
                    for b in (job.interview_baseline or [])]
        try:
            generated = await generate_probes(
                profile=candidate.summary or candidate.full_name or "",
                criteria=[CriteriaItem.model_validate(c) for c in (job.criteria or [])],
                score_breakdown=app_row.score_breakdown,
                baseline=baseline,
                llm=llm,
            )
            texts = [q.text for q in generated.questions]
            criteria_by_probe = [q.criterion for q in generated.questions]
            existing_raw = app_row.interview_kit or {}
            existing_questions = existing_raw.get("questions") or []
            if existing_questions:
                kit = merge_regenerated(
                    InterviewKit.model_validate(existing_raw), baseline, texts,
                    criteria_by_probe=criteria_by_probe, now=_now(),
                )
            else:
                kit = build_kit(baseline, texts,
                                 criteria_by_probe=criteria_by_probe, now=_now())
        except Exception as exc:  # noqa: BLE001 — recorded, not swallowed
            logger.warning("interview kit generation failed: %s", exc, exc_info=True)
            kit = InterviewKit(status="error", error=str(exc)[:500])
        app_row.interview_kit = kit.model_dump()
        await session.commit()
    await bus.publish({
        "type": "interview_kit", "application_id": application_id, "status": kit.status,
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

    existing = app_row.interview_kit or {}
    app_row.interview_kit = {**existing, "status": "generating", "error": None,
                              "questions": existing.get("questions") or []}
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
) -> InterviewKitRead:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    if not app_row.interview_kit:
        raise HTTPException(
            status_code=404, detail="no interview kit; generate one first"
        )

    ids = [q.id for q in payload.questions]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="duplicate question ids")

    kit = InterviewKit.model_validate(app_row.interview_kit)
    kit.questions = payload.questions
    app_row.interview_kit = kit.model_dump()
    await session.commit()
    return InterviewKitRead(kit=kit)


@router.post("/applications/{application_id}/interview-kit/submit",
             response_model=InterviewKitRead)
async def submit_kit(
    application_id: int,
    session: AsyncSession = Depends(get_session),
) -> InterviewKitRead:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    if not app_row.interview_kit:
        raise HTTPException(status_code=404, detail="no interview kit; "
                            "generate one first")

    kit = InterviewKit.model_validate(app_row.interview_kit)
    kit.submitted_at = _now()
    app_row.interview_kit = kit.model_dump()

    # Advance only from SCHEDULED. Already interviewed or beyond means this
    # is an edit to a past interview, not a new one — re-submitting must not
    # push the candidate further down the pipeline.
    if app_row.stage == Stage.SCHEDULED:
        app_row.stage = Stage.INTERVIEWED
        app_row.interviewed_at = datetime.now(UTC)

    await session.commit()
    return InterviewKitRead(kit=kit)
