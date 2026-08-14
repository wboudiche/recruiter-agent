"""Every pipeline failure must stay diagnosable.

An exception raised without a message (`TimeoutError()`, `CancelledError`,
…) stringifies to "". Recording that verbatim produces `{"error": ""}` —
indistinguishable from "no error" — and the card sits on its stage with
nothing to debug. Real incidents cost hours to this exact hole, so each
handler is pinned here, not just the one that happened to be found first.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.events import EventBus
from recruiter.llm.client import FakeLLMClient
from recruiter.models import Application, Candidate, EventLog, Job, Stage
from recruiter.pipeline.orchestrator import process_application
from recruiter.pipeline.router import RoutedInput
from recruiter.schemas.extraction import ExtractedCandidate


class _SilentBoom(Exception):
    """Raised with no args, so `str(exc)` is empty — like a bare TimeoutError."""


async def _seed(session: AsyncSession) -> Application:
    job = Job(
        title="Backend", description="Rust",
        criteria=[{"name": "Rust", "weight": 1.0, "description": "y"}],
    )
    candidate = Candidate(full_name=None)
    session.add_all([job, candidate])
    await session.flush()
    app = Application(job_id=job.id, candidate_id=candidate.id, stage=Stage.EXTRACTING)
    session.add(app)
    await session.commit()
    return app


async def _events(session: AsyncSession, app_id: int, event_type: str) -> list[dict]:
    rows = (await session.execute(
        select(EventLog).where(EventLog.application_id == app_id, EventLog.event_type == event_type)
    )).scalars().all()
    return [r.payload for r in rows]


@pytest.mark.asyncio
async def test_messageless_extraction_failure_records_the_exception_type(
    db_session_with_schema: AsyncSession, monkeypatch,
) -> None:
    app = await _seed(db_session_with_schema)

    async def boom(**_kw):
        raise _SilentBoom

    monkeypatch.setattr("recruiter.pipeline.orchestrator.extract_candidate", boom)

    engine = db_session_with_schema.bind
    assert engine is not None
    await process_application(
        application_id=app.id,
        routed=RoutedInput(kind="paste", text="x", source_url=None, resume_path=None),
        engine=engine,  # type: ignore[arg-type]
        llm=FakeLLMClient(),
        bus=EventBus(),
    )

    payloads = await _events(db_session_with_schema, app.id, "extract.failed")
    assert payloads and payloads[0]["error"] == "_SilentBoom"


@pytest.mark.asyncio
async def test_messageless_scoring_failure_records_the_exception_type(
    db_session_with_schema: AsyncSession, monkeypatch,
) -> None:
    """Scoring calls the same LLM as extraction, so it meets the same
    rate limits and timeouts — and strands the card just as hard."""
    app = await _seed(db_session_with_schema)

    async def boom(**_kw):
        raise _SilentBoom

    monkeypatch.setattr("recruiter.pipeline.orchestrator.score_candidate", boom)

    engine = db_session_with_schema.bind
    assert engine is not None
    await process_application(
        application_id=app.id,
        routed=RoutedInput(kind="paste", text="x", source_url=None, resume_path=None),
        engine=engine,  # type: ignore[arg-type]
        llm=FakeLLMClient(
            structured_responses=[ExtractedCandidate(full_name="A", skills=["Rust"])],
        ),
        bus=EventBus(),
    )

    payloads = await _events(db_session_with_schema, app.id, "score.failed")
    assert payloads and payloads[0]["error"] == "_SilentBoom"
