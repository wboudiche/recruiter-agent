"""`last_error` surfaces why the pipeline stopped, so the UI can say more
than "Extracting" and decide whether Retry is worth offering."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.models import Application, Candidate, EventLog, Job, Stage


async def _seed(session: AsyncSession) -> Application:
    job = Job(title="T", description="D", criteria=[])
    candidate = Candidate(full_name=None)
    session.add_all([job, candidate])
    await session.flush()
    app_row = Application(job_id=job.id, candidate_id=candidate.id, stage=Stage.EXTRACTING)
    session.add(app_row)
    await session.commit()
    return app_row


@pytest.mark.asyncio
async def test_last_error_reports_the_newest_failure(
    api_client: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_row = await _seed(db_session_with_schema)
    db_session_with_schema.add(EventLog(
        application_id=app_row.id,
        event_type="extract.failed",
        payload={"error": "HTTP 429 rate-limited"},
    ))
    await db_session_with_schema.commit()

    body = (await api_client.get(f"/api/applications/{app_row.id}")).json()

    assert body["last_error"] == "HTTP 429 rate-limited"


@pytest.mark.asyncio
async def test_last_error_clears_once_a_later_event_succeeds(
    api_client: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    """A successful retry writes a newer event; the flag must self-heal
    rather than pin the card to a stale failure."""
    app_row = await _seed(db_session_with_schema)
    db_session_with_schema.add(EventLog(
        application_id=app_row.id, event_type="extract.failed", payload={"error": "boom"},
    ))
    await db_session_with_schema.commit()
    db_session_with_schema.add(EventLog(
        application_id=app_row.id, event_type="application.scored", payload={"score": 42},
    ))
    await db_session_with_schema.commit()

    body = (await api_client.get(f"/api/applications/{app_row.id}")).json()

    assert body["last_error"] is None


@pytest.mark.asyncio
async def test_last_error_is_none_when_nothing_has_happened(
    api_client: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_row = await _seed(db_session_with_schema)

    body = (await api_client.get(f"/api/applications/{app_row.id}")).json()

    assert body["last_error"] is None


@pytest.mark.asyncio
async def test_list_endpoint_includes_last_error(
    api_client: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_row = await _seed(db_session_with_schema)
    db_session_with_schema.add(EventLog(
        application_id=app_row.id, event_type="score.failed", payload={"error": "ReadTimeout"},
    ))
    await db_session_with_schema.commit()

    rows = (await api_client.get(f"/api/jobs/{app_row.job_id}/applications")).json()

    assert [r["last_error"] for r in rows if r["id"] == app_row.id] == ["ReadTimeout"]


@pytest.mark.asyncio
async def test_list_endpoint_does_not_query_per_application(
    api_client: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    """`_to_read` runs per row, so a per-row error lookup would be N+1.
    The count must not grow with the number of applications on the board."""
    from sqlalchemy import event as sa_event

    from recruiter.api.candidates import get_engine_dep
    from recruiter.main import app

    first = await _seed(db_session_with_schema)
    # Each extra application needs its own candidate: `applications` has a
    # unique constraint on (job_id, candidate_id), so reusing first's
    # candidate here would violate it rather than exercise the N+1 check.
    extra_candidates = [Candidate(full_name=None) for _ in range(4)]
    db_session_with_schema.add_all(extra_candidates)
    await db_session_with_schema.flush()
    for candidate in extra_candidates:
        extra = Application(
            job_id=first.job_id, candidate_id=candidate.id, stage=Stage.EXTRACTING,
        )
        db_session_with_schema.add(extra)
    await db_session_with_schema.commit()

    # `db_session_with_schema` and `api_client` are backed by two distinct
    # AsyncEngine instances (see tests/conftest.py vs tests/api/conftest.py),
    # even though both point at the same physical database. A listener on
    # the fixture's engine would never see the API request's SQL — so pull
    # the engine the API layer is actually using, which `api_client` has
    # registered as a dependency override.
    engine = app.dependency_overrides[get_engine_dep]()
    assert engine is not None
    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    sa_event.listen(engine.sync_engine, "before_cursor_execute", _record)
    try:
        await api_client.get(f"/api/jobs/{first.job_id}/applications")
    finally:
        sa_event.remove(engine.sync_engine, "before_cursor_execute", _record)

    event_log_queries = [s for s in statements if "event_logs" in s.lower()]
    assert len(event_log_queries) <= 1, f"expected one batched query, got {len(event_log_queries)}"
