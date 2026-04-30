from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from recruiter.events import EventBus
from recruiter.llm.client import LLMClient
from recruiter.models import Application, Candidate, EventLog, Job, Stage
from recruiter.pipeline.extractor import extract_candidate
from recruiter.pipeline.router import RoutedInput
from recruiter.pipeline.scorer import score_candidate
from recruiter.schemas.extraction import ExtractedCandidate
from recruiter.schemas.job import CriteriaItem


async def process_application(
    *,
    application_id: int,
    routed: RoutedInput,
    engine: AsyncEngine,
    llm: LLMClient,
    bus: EventBus,
) -> None:
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionLocal() as session:
        app = await session.get(Application, application_id)
        if app is None:
            return
        job = await session.get(Job, app.job_id)
        candidate = await session.get(Candidate, app.candidate_id)
        if job is None or candidate is None:
            return

        await bus.publish({"type": "stage", "application_id": app.id, "stage": Stage.EXTRACTING.value})

        text = routed.text or ""
        # Persist raw text up-front so retry can re-run even if extraction fails.
        candidate.raw_extracted = {"text": text, "structured": None}
        if routed.source_url is not None:
            candidate.source_url = routed.source_url
        if routed.resume_path is not None:
            candidate.resume_path = routed.resume_path
        await session.flush()

        try:
            extracted = await extract_candidate(text=text, llm=llm)
        except Exception as exc:
            session.add(EventLog(application_id=app.id, event_type="extract.failed", payload={"error": str(exc)}))
            await session.commit()
            await bus.publish({"type": "error", "application_id": app.id, "phase": "extract", "error": str(exc)})
            return

        _apply_extracted(candidate, extracted, raw_text=text, source_url=routed.source_url, resume_path=routed.resume_path)
        await session.flush()

        criteria = [CriteriaItem.model_validate(c) for c in (job.criteria or [])]
        try:
            score = await score_candidate(
                job_title=job.title,
                job_description=job.description,
                criteria=criteria,
                candidate=extracted,
                llm=llm,
            )
        except Exception as exc:
            session.add(EventLog(application_id=app.id, event_type="score.failed", payload={"error": str(exc)}))
            await session.commit()
            await bus.publish({"type": "error", "application_id": app.id, "phase": "score", "error": str(exc)})
            return

        app.score = score.score
        app.score_breakdown = [item.model_dump() for item in score.breakdown]
        app.score_rationale = score.rationale
        app.stage = Stage.SCORED
        session.add(EventLog(application_id=app.id, event_type="application.scored", payload={"score": score.score}))
        await session.commit()

    await bus.publish({"type": "stage", "application_id": application_id, "stage": Stage.SCORED.value, "score": score.score})


def _apply_extracted(
    candidate: Candidate,
    extracted: ExtractedCandidate,
    *,
    raw_text: str,
    source_url: str | None,
    resume_path: str | None,
) -> None:
    candidate.full_name = extracted.full_name or candidate.full_name
    candidate.email = extracted.email or candidate.email
    candidate.phone = extracted.phone or candidate.phone
    candidate.location = extracted.location or candidate.location
    candidate.headline = extracted.headline or candidate.headline
    candidate.summary = extracted.summary or candidate.summary
    if extracted.skills:
        candidate.skills = extracted.skills
    if extracted.experience:
        candidate.experience = [item.model_dump() for item in extracted.experience]
    if extracted.education:
        candidate.education = [item.model_dump() for item in extracted.education]
    if extracted.links:
        candidate.links = [item.model_dump() for item in extracted.links]
    candidate.raw_extracted = {"text": raw_text, "structured": extracted.model_dump()}
    if source_url is not None:
        candidate.source_url = source_url
    if resume_path is not None:
        candidate.resume_path = resume_path
