from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from recruiter.enrichment.pipeline import enrich
from recruiter.events import EventBus
from recruiter.llm.client import LLMClient
from recruiter.models import Application, Candidate, EventLog, Job, SettingsRow, Stage
from recruiter.pipeline.extractor import extract_candidate
from recruiter.pipeline.router import RoutedInput
from recruiter.pipeline.scorer import score_candidate
from recruiter.schemas.extraction import ExtractedCandidate
from recruiter.schemas.job import CriteriaItem


async def re_enrich_application(
    *,
    application_id: int,
    engine: AsyncEngine,
    llm: LLMClient,
    bus: EventBus,
) -> None:
    """Re-run ONLY the enrichment step for an already-extracted candidate.

    The full `process_application` re-runs fetch + extract + score in
    addition to enrich, which is the wrong default for a "refresh
    enrichment" user action — if extract fails (e.g. the raw text is
    empty or the LLM hiccups) the candidate gets stuck in `enriching`
    with no score change available.

    This entry point loads the existing candidate, runs the enrichment
    pipeline, persists the result, and restores the stage to SCORED
    on success (or back to whatever it was on failure).
    """
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        app = await session.get(Application, application_id)
        if app is None:
            return
        candidate = await session.get(Candidate, app.candidate_id)
        if candidate is None:
            return
        job = await session.get(Job, app.job_id)
        if job is None:
            return

        prior_stage = app.stage
        settings_row = await session.get(SettingsRow, 1)
        if settings_row is None or not settings_row.enrichment_enabled:
            # Enrichment globally disabled — nothing to do, restore stage.
            app.stage = prior_stage if prior_stage != Stage.ENRICHING else Stage.SCORED
            await session.commit()
            return

        await bus.publish({
            "type": "stage", "application_id": app.id, "stage": Stage.ENRICHING.value,
        })
        app.stage = Stage.ENRICHING
        await session.commit()

        try:
            bundle = await enrich(
                candidate=candidate, job=job, settings=settings_row, llm=llm,
            )
            app.enrichment = bundle.model_dump(mode="json")
            session.add(EventLog(
                application_id=app.id,
                event_type="application.enriched",
                payload={"results": len(bundle.results), "errors": len(bundle.errors)},
            ))
        except Exception as exc:
            session.add(EventLog(
                application_id=app.id,
                event_type="enrichment.failed",
                payload={"error": str(exc) or type(exc).__name__},
            ))

        # Restore: scored candidates go back to scored regardless of
        # enrichment success (it's a non-fatal step). Unscored candidates
        # keep their prior stage so we don't lie about progress.
        app.stage = Stage.SCORED if app.score is not None else prior_stage
        await session.commit()

    await bus.publish({
        "type": "stage", "application_id": application_id,
        "stage": (Stage.SCORED if app.score is not None else prior_stage).value,
    })


def _has_fresh_bundle(app: Application) -> bool:
    """True when the persisted enrichment bundle is still within TTL."""
    if not app.enrichment:
        return False
    expires_at = app.enrichment.get("expires_at")
    if not expires_at:
        return False
    try:
        if isinstance(expires_at, datetime):
            ts = expires_at
        else:
            ts = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts > datetime.now(UTC)


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

        # ----- enrichment stage (additive; score is unchanged) -----
        bundle = None
        settings_row = await session.get(SettingsRow, 1)
        if (
            settings_row is not None
            and settings_row.enrichment_enabled
            and not _has_fresh_bundle(app)
        ):
            await bus.publish({"type": "stage", "application_id": app.id, "stage": Stage.ENRICHING.value})
            app.stage = Stage.ENRICHING
            await session.commit()
            try:
                bundle = await enrich(
                    candidate=candidate, job=job, settings=settings_row, llm=llm
                )
                app.enrichment = bundle.model_dump(mode="json")
                session.add(EventLog(
                    application_id=app.id,
                    event_type="application.enriched",
                    payload={
                        "results": len(bundle.results),
                        "errors": len(bundle.errors),
                    },
                ))
                await session.commit()
            except Exception as exc:
                session.add(EventLog(
                    application_id=app.id,
                    event_type="enrichment.failed",
                    payload={"error": str(exc)},
                ))
                await session.commit()
                # Non-fatal: scoring proceeds.

        # ----- scoring (UNCHANGED — same arguments as before) -----
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
