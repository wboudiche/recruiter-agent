import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.models import Application, Candidate, Job, Stage


@pytest.mark.asyncio
async def test_application_enrichment_field_round_trips(
    db_session_with_schema: AsyncSession,
) -> None:
    """The new JSON column survives a write/read cycle."""
    job = Job(title="t", description="d", criteria=[], enrichment_consent=True)
    cand = Candidate(full_name="Alice")
    db_session_with_schema.add_all([job, cand])
    await db_session_with_schema.flush()
    app = Application(
        job_id=job.id,
        candidate_id=cand.id,
        stage=Stage.ENRICHING,
        enrichment={"results": [{"source": "github", "confidence": 1.0}]},
    )
    db_session_with_schema.add(app)
    await db_session_with_schema.commit()

    fetched = (
        await db_session_with_schema.execute(
            select(Application).where(Application.id == app.id)
        )
    ).scalar_one()
    assert fetched.stage == Stage.ENRICHING
    assert fetched.enrichment == {"results": [{"source": "github", "confidence": 1.0}]}


@pytest.mark.asyncio
async def test_application_enrichment_defaults_to_none(
    db_session_with_schema: AsyncSession,
) -> None:
    job = Job(title="t", description="d", criteria=[])
    cand = Candidate()
    db_session_with_schema.add_all([job, cand])
    await db_session_with_schema.flush()
    app = Application(job_id=job.id, candidate_id=cand.id, stage=Stage.EXTRACTING)
    db_session_with_schema.add(app)
    await db_session_with_schema.commit()
    assert app.enrichment is None


@pytest.mark.asyncio
async def test_job_enrichment_consent_default_false(
    db_session_with_schema: AsyncSession,
) -> None:
    job = Job(title="t", description="d", criteria=[])
    db_session_with_schema.add(job)
    await db_session_with_schema.commit()
    assert job.enrichment_consent is False


def test_stage_enum_includes_enriching() -> None:
    assert Stage.ENRICHING.value == "enriching"
    assert Stage("enriching") is Stage.ENRICHING
