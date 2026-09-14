import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.models import (
    Application,
    Candidate,
    InterviewAssignment,
    Job,
    Role,
    Stage,
    User,
)


async def _seed(session: AsyncSession) -> tuple[int, int]:
    job = Job(title="Backend", description="x", criteria=[])
    session.add(job)
    await session.flush()
    cand = Candidate(source_type="paste", full_name="Marie", email="m@example.com")
    session.add(cand)
    await session.flush()
    app_row = Application(job_id=job.id, candidate_id=cand.id, stage=Stage.SCHEDULED)
    user = User(email="a@acme.com", role=Role.VIEWER, is_active=True)
    session.add_all([app_row, user])
    await session.commit()
    return app_row.id, user.id


@pytest.mark.asyncio
async def test_assignment_round_trips_and_defaults_to_empty_sheet(
    db_session_with_schema: AsyncSession,
) -> None:
    app_id, user_id = await _seed(db_session_with_schema)
    db_session_with_schema.add(InterviewAssignment(application_id=app_id, user_id=user_id))
    await db_session_with_schema.commit()
    row = (await db_session_with_schema.execute(
        select(InterviewAssignment).where(InterviewAssignment.application_id == app_id)
    )).scalar_one()
    assert row.user_id == user_id
    assert row.sheet == {"answers": {}, "verdict": {"decision": None, "note": None}}
    assert row.submitted_at is None


@pytest.mark.asyncio
async def test_one_row_per_application_and_user(db_session_with_schema: AsyncSession) -> None:
    app_id, user_id = await _seed(db_session_with_schema)
    db_session_with_schema.add(InterviewAssignment(application_id=app_id, user_id=user_id))
    await db_session_with_schema.commit()
    db_session_with_schema.add(InterviewAssignment(application_id=app_id, user_id=user_id))
    with pytest.raises(IntegrityError):
        await db_session_with_schema.commit()


@pytest.mark.asyncio
async def test_deleting_the_application_deletes_assignments(
    db_session_with_schema: AsyncSession,
) -> None:
    app_id, user_id = await _seed(db_session_with_schema)
    db_session_with_schema.add(InterviewAssignment(application_id=app_id, user_id=user_id))
    await db_session_with_schema.commit()
    app_row = await db_session_with_schema.get(Application, app_id)
    await db_session_with_schema.delete(app_row)
    await db_session_with_schema.commit()
    left = (await db_session_with_schema.execute(select(InterviewAssignment))).scalars().all()
    assert left == []


@pytest.mark.asyncio
async def test_deleting_the_user_deletes_their_assignments(
    db_session_with_schema: AsyncSession,
) -> None:
    app_id, user_id = await _seed(db_session_with_schema)
    db_session_with_schema.add(InterviewAssignment(application_id=app_id, user_id=user_id))
    await db_session_with_schema.commit()
    user = await db_session_with_schema.get(User, user_id)
    await db_session_with_schema.delete(user)
    await db_session_with_schema.commit()
    left = (await db_session_with_schema.execute(select(InterviewAssignment))).scalars().all()
    assert left == []
