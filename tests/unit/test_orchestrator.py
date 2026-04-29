from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.events import EventBus
from recruiter.llm.client import FakeLLMClient
from recruiter.models import Application, Candidate, Job, Stage
from recruiter.pipeline.orchestrator import process_application
from recruiter.pipeline.router import RoutedInput
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult


@pytest.mark.asyncio
async def test_process_application_extracts_scores_and_advances_stage(db_session_with_schema: AsyncSession) -> None:
    job = Job(title="Backend", description="Rust APIs", criteria=[{"name": "Rust", "weight": 1.0, "description": "yrs"}])
    candidate = Candidate(full_name=None)
    db_session_with_schema.add_all([job, candidate])
    await db_session_with_schema.flush()

    app = Application(job_id=job.id, candidate_id=candidate.id, stage=Stage.EXTRACTING)
    db_session_with_schema.add(app)
    await db_session_with_schema.commit()

    fake = FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice", email="a@b.c", skills=["Rust"]),
            ScoreResult(
                score=85,
                breakdown=[ScoreBreakdownItem(criterion="Rust", weight=1.0, score=85, rationale="ok")],
                rationale="great",
            ),
        ]
    )
    bus = EventBus()
    events: list[dict] = []

    async def listener(payload: dict) -> None:
        events.append(payload)

    bus.subscribe(listener)

    routed = RoutedInput(kind="paste", text="Alice — Rust", source_url=None, resume_path=None)

    engine = db_session_with_schema.bind
    assert engine is not None
    await process_application(
        application_id=app.id,
        routed=routed,
        engine=engine,  # type: ignore[arg-type]
        llm=fake,
        bus=bus,
    )

    # Orchestrator commits via its own session; refresh ours so we re-read from DB.
    await db_session_with_schema.refresh(app)
    await db_session_with_schema.refresh(candidate)

    assert app.stage == Stage.SCORED
    assert app.score == 85
    assert candidate.full_name == "Alice"

    stage_events = [e["stage"] for e in events if e.get("type") == "stage"]
    assert stage_events == ["extracting", "scored"]
