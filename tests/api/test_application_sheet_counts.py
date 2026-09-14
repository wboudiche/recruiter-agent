from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from recruiter.api.candidates import get_engine_dep
from recruiter.main import app
from recruiter.models import Application, InterviewAssignment, Role, User


@pytest.mark.asyncio
async def test_reads_carry_sheet_counts(api_client: AsyncClient, create_scored_app) -> None:
    app_id = await create_scored_app()
    sessionmaker = async_sessionmaker(
        app.dependency_overrides[get_engine_dep](), expire_on_commit=False,
    )
    async with sessionmaker() as s:
        a = User(email="a@acme.com", role=Role.VIEWER, is_active=True)
        b = User(email="b@acme.com", role=Role.VIEWER, is_active=True)
        s.add_all([a, b])
        await s.flush()
        s.add_all([
            InterviewAssignment(
                application_id=app_id, user_id=a.id, submitted_at=datetime.now(UTC),
            ),
            InterviewAssignment(application_id=app_id, user_id=b.id),
        ])
        await s.commit()
        job_id = (await s.get(Application, app_id)).job_id

    one = (await api_client.get(f"/api/applications/{app_id}")).json()
    assert (one["sheets_total"], one["sheets_submitted"]) == (2, 1)
    many = (await api_client.get(f"/api/jobs/{job_id}/applications")).json()
    assert (many[0]["sheets_total"], many[0]["sheets_submitted"]) == (2, 1)


@pytest.mark.asyncio
async def test_counts_default_to_zero(api_client: AsyncClient, create_scored_app) -> None:
    app_id = await create_scored_app()
    one = (await api_client.get(f"/api/applications/{app_id}")).json()
    assert (one["sheets_total"], one["sheets_submitted"]) == (0, 0)
