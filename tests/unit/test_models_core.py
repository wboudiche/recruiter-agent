import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.models import Application, Candidate, Job, Stage


@pytest.mark.asyncio
async def test_create_job_and_application_roundtrip(db_session_with_schema: AsyncSession) -> None:
    job = Job(title="Backend Engineer", description="Build APIs", criteria=[])
    candidate = Candidate(full_name="Alice", email="alice@example.com")
    db_session_with_schema.add_all([job, candidate])
    await db_session_with_schema.flush()

    app_row = Application(
        job_id=job.id,
        candidate_id=candidate.id,
        stage=Stage.EXTRACTING,
    )
    db_session_with_schema.add(app_row)
    await db_session_with_schema.commit()

    fetched = await db_session_with_schema.get(Application, app_row.id)
    assert fetched is not None
    assert fetched.stage == Stage.EXTRACTING
    assert fetched.job_id == job.id
