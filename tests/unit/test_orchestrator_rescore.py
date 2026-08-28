import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.models import Application, Candidate, Job, Stage
from recruiter.pipeline.orchestrator import rescore_applications_for_job
from recruiter.pipeline.scorer import ScoreResult


class _FakeBus:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, ev: dict) -> None:
        self.events.append(ev)


class _ScoringLLM:
    """Records the criteria it was scored against and returns a score
    derived from them, so tests can assert the new criteria were used."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def chat(self, *a, **kw):
        raise NotImplementedError

    async def chat_structured(self, *a, messages, schema, **kw):
        self.calls.append({"messages": messages})
        return ScoreResult(score=42, breakdown=[], rationale="rescored")


@pytest.mark.asyncio
async def test_rescore_updates_score_for_already_scored_application(
    db_session_with_schema: AsyncSession,
) -> None:
    session = db_session_with_schema
    engine = session.bind
    assert engine is not None

    job = Job(
        title="Rust dev",
        description="d",
        criteria=[{"name": "Rust", "weight": 1.0, "description": "Rust experience"}],
    )
    cand = Candidate(full_name="Alice", skills=["python"])
    session.add_all([job, cand])
    await session.flush()
    app = Application(
        job_id=job.id,
        candidate_id=cand.id,
        stage=Stage.SCORED,
        score=10,
        score_breakdown=[{"criterion": "old", "weight": 1.0, "score": 10, "rationale": "stale"}],
        score_rationale="stale rationale",
    )
    session.add(app)
    await session.commit()

    llm = _ScoringLLM()
    bus = _FakeBus()

    await rescore_applications_for_job(job_id=job.id, engine=engine, llm=llm, bus=bus)  # type: ignore[arg-type]

    await session.refresh(app)
    assert app.score == 42
    assert app.score_rationale == "rescored"
    assert app.stage == Stage.SCORED
    assert any(e.get("type") == "stage" and e.get("score") == 42 for e in bus.events)


@pytest.mark.asyncio
async def test_rescore_skips_applications_without_an_existing_score(
    db_session_with_schema: AsyncSession,
) -> None:
    """An application still mid-pipeline (never scored) has nothing stale
    to fix — it'll score against current criteria on its own."""
    session = db_session_with_schema
    engine = session.bind
    assert engine is not None

    job = Job(title="Rust dev", description="d", criteria=[])
    cand = Candidate(full_name="Bob")
    session.add_all([job, cand])
    await session.flush()
    app = Application(job_id=job.id, candidate_id=cand.id, stage=Stage.EXTRACTING, score=None)
    session.add(app)
    await session.commit()

    llm = _ScoringLLM()
    bus = _FakeBus()

    await rescore_applications_for_job(job_id=job.id, engine=engine, llm=llm, bus=bus)  # type: ignore[arg-type]

    assert llm.calls == []
    await session.refresh(app)
    assert app.score is None
    assert app.stage == Stage.EXTRACTING
