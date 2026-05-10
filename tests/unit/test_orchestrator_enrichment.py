import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.models import Application, Candidate, Job, SettingsRow, Stage
from recruiter.pipeline.orchestrator import process_application
from recruiter.pipeline.router import RoutedInput


class _FakeBus:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, ev: dict) -> None:
        self.events.append(ev)


class _FakeLLM:
    """Minimal LLM stub. Records calls so we can assert score args don't
    include enrichment data."""

    def __init__(self) -> None:
        self.score_calls: list = []

    async def chat(self, *a, **kw):
        return ""

    async def chat_structured(self, *a, **kw):
        # When called from scorer, record the messages for inspection.
        self.score_calls.append((a, kw))
        from recruiter.pipeline.scorer import ScoreResult

        return ScoreResult(score=85, breakdown=[], rationale="ok")


@pytest.mark.asyncio
async def test_score_args_identical_with_and_without_enrichment(
    db_session_with_schema: AsyncSession, monkeypatch
) -> None:
    """Decision 1 invariant: score_candidate is invoked with the same
    arguments whether enrichment ran or not."""
    session = db_session_with_schema
    engine = session.bind
    assert engine is not None

    job = Job(title="Rust", description="d", criteria=[], enrichment_consent=False)
    cand = Candidate(full_name="Alice")
    session.add_all([job, cand])
    await session.flush()
    app = Application(job_id=job.id, candidate_id=cand.id, stage=Stage.EXTRACTING)
    session.add(app)
    settings_row = SettingsRow(id=1, enrichment_enabled=False)
    session.add(settings_row)
    await session.commit()

    captured: list[dict] = []

    async def spy_score(**kwargs):
        captured.append(dict(kwargs))
        from recruiter.pipeline.scorer import ScoreResult

        return ScoreResult(score=85, breakdown=[], rationale="ok")

    monkeypatch.setattr("recruiter.pipeline.orchestrator.score_candidate", spy_score)
    # Patch extractor so we don't hit the LLM.
    from recruiter.schemas.extraction import ExtractedCandidate

    async def fake_extract(*a, **kw):
        return ExtractedCandidate(
            full_name="Alice", skills=[], experience=[], education=[], links=[]
        )

    monkeypatch.setattr(
        "recruiter.pipeline.orchestrator.extract_candidate", fake_extract
    )

    bus = _FakeBus()
    llm = _FakeLLM()

    # Run 1: enrichment OFF
    await process_application(
        application_id=app.id,
        routed=RoutedInput(kind="paste", text="x", source_url=None, resume_path=None),
        engine=engine,  # type: ignore[arg-type]
        llm=llm,
        bus=bus,
    )
    args_off = captured[-1]

    # Reset app stage so we can re-process.
    await session.refresh(app)
    await session.refresh(settings_row)
    app.stage = Stage.EXTRACTING
    settings_row.enrichment_enabled = True
    await session.commit()

    # Run 2: enrichment ON (but no providers configured -> no results)
    monkeypatch.setattr(
        "recruiter.enrichment.pipeline._resolve_providers", lambda *a, **k: []
    )
    await process_application(
        application_id=app.id,
        routed=RoutedInput(kind="paste", text="x", source_url=None, resume_path=None),
        engine=engine,  # type: ignore[arg-type]
        llm=llm,
        bus=bus,
    )
    args_on = captured[-1]

    # The score args must be byte-identical between the two runs.
    assert args_off == args_on


@pytest.mark.asyncio
async def test_enrichment_failure_does_not_break_scoring(
    db_session_with_schema: AsyncSession, monkeypatch
) -> None:
    """If enrich() raises, the orchestrator logs and continues to score."""
    session = db_session_with_schema
    engine = session.bind
    assert engine is not None

    job = Job(title="t", description="d", criteria=[], enrichment_consent=True)
    cand = Candidate(full_name="Alice")
    session.add_all([job, cand])
    await session.flush()
    app = Application(job_id=job.id, candidate_id=cand.id, stage=Stage.EXTRACTING)
    session.add(app)
    session.add(SettingsRow(id=1, enrichment_enabled=True))
    await session.commit()

    from recruiter.schemas.extraction import ExtractedCandidate

    async def fake_extract(*a, **kw):
        return ExtractedCandidate(
            full_name="Alice", skills=[], experience=[], education=[], links=[]
        )

    monkeypatch.setattr(
        "recruiter.pipeline.orchestrator.extract_candidate", fake_extract
    )

    async def crash(**kw):
        raise RuntimeError("boom")

    monkeypatch.setattr("recruiter.pipeline.orchestrator.enrich", crash)

    scored = False

    async def fake_score(**kw):
        nonlocal scored
        scored = True
        from recruiter.pipeline.scorer import ScoreResult

        return ScoreResult(score=70, breakdown=[], rationale="ok")

    monkeypatch.setattr("recruiter.pipeline.orchestrator.score_candidate", fake_score)

    await process_application(
        application_id=app.id,
        routed=RoutedInput(kind="paste", text="x", source_url=None, resume_path=None),
        engine=engine,  # type: ignore[arg-type]
        llm=_FakeLLM(),
        bus=_FakeBus(),
    )
    assert scored is True


@pytest.mark.asyncio
async def test_fresh_bundle_within_ttl_is_reused(
    db_session_with_schema: AsyncSession, monkeypatch
) -> None:
    """If application.enrichment.expires_at is in the future, skip enrichment."""
    from datetime import UTC, datetime, timedelta

    session = db_session_with_schema
    engine = session.bind
    assert engine is not None

    future = (datetime.now(UTC) + timedelta(days=10)).isoformat()

    job = Job(title="t", description="d", criteria=[], enrichment_consent=True)
    cand = Candidate(full_name="Alice")
    session.add_all([job, cand])
    await session.flush()
    app = Application(
        job_id=job.id,
        candidate_id=cand.id,
        stage=Stage.EXTRACTING,
        enrichment={
            "expires_at": future,
            "results": [],
            "errors": [],
            "discovery_consent": True,
            "fetched_at": datetime.now(UTC).isoformat(),
        },
    )
    session.add(app)
    session.add(SettingsRow(id=1, enrichment_enabled=True))
    await session.commit()

    from recruiter.schemas.extraction import ExtractedCandidate

    async def fake_extract(*a, **kw):
        return ExtractedCandidate(
            full_name="Alice", skills=[], experience=[], education=[], links=[]
        )

    monkeypatch.setattr(
        "recruiter.pipeline.orchestrator.extract_candidate", fake_extract
    )

    enrich_called = False

    async def fake_enrich(**kw):
        nonlocal enrich_called
        enrich_called = True
        from recruiter.enrichment.provider import EnrichmentBundle

        return EnrichmentBundle(
            fetched_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=30),
            discovery_consent=True,
            results=[],
            errors=[],
        )

    monkeypatch.setattr("recruiter.pipeline.orchestrator.enrich", fake_enrich)

    async def fake_score(**kw):
        from recruiter.pipeline.scorer import ScoreResult

        return ScoreResult(score=70, breakdown=[], rationale="ok")

    monkeypatch.setattr("recruiter.pipeline.orchestrator.score_candidate", fake_score)

    await process_application(
        application_id=app.id,
        routed=RoutedInput(kind="paste", text="x", source_url=None, resume_path=None),
        engine=engine,  # type: ignore[arg-type]
        llm=_FakeLLM(),
        bus=_FakeBus(),
    )
    assert enrich_called is False
