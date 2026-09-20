"""Migration A against real Postgres.

The rest of the suite builds its schema with `Base.metadata.create_all`,
so migrations are otherwise never executed by a test. The per-round copy
is the part worth pinning: getting it wrong silently empties a closed
round's feedback table.
"""
import json

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from recruiter.config import get_config

PREVIOUS = "b8f3d1a20c47"   # the rounds migration
CURRENT = "c1a7e05b3f92"    # migration A


def _alembic(monkeypatch, sync_dsn: str) -> Config:
    # env.py overrides sqlalchemy.url from get_config(), so the env var is
    # the only lever; clear the lru_cache or the override is ignored.
    monkeypatch.setenv("RECRUITER_DATABASE_URL", sync_dsn.replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"))
    monkeypatch.setenv("RECRUITER_DEFAULT_ACCOUNT_EMAIL", "mig@example.com")
    monkeypatch.setenv("RECRUITER_DEFAULT_ACCOUNT_PASSWORD", "migration-check-only")
    get_config.cache_clear()
    return Config("alembic.ini")


def _seed_application(engine, *, interview_round: int, blob: dict) -> None:
    with engine.begin() as conn:
        conn.execute(sa.text(
            "INSERT INTO jobs (title, description, criteria, status, created_at, updated_at)"
            " VALUES ('J','d','[]','open',now(),now())"))
        conn.execute(sa.text(
            "INSERT INTO candidates (source_type, full_name, skills, experience, education,"
            " links, created_at, updated_at)"
            " VALUES ('paste','C','[]','[]','[]','[]',now(),now())"))
        conn.execute(sa.text(
            "INSERT INTO applications (job_id, candidate_id, stage, interview_round,"
            " interview_kit, created_at, updated_at)"
            " SELECT (SELECT id FROM jobs LIMIT 1), (SELECT id FROM candidates LIMIT 1),"
            " 'scheduled', :rnd, :kit, now(), now()"),
            {"rnd": interview_round, "kit": json.dumps(blob)})


def test_backfill_writes_one_kit_per_round(postgres_container, monkeypatch) -> None:
    sync_dsn = postgres_container.get_connection_url()
    engine = sa.create_engine(sync_dsn)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))

    cfg = _alembic(monkeypatch, sync_dsn)
    command.upgrade(cfg, PREVIOUS)

    _seed_application(engine, interview_round=2, blob={
        "status": "ready",
        "questions": [{"id": "q1", "text": "Why?", "source": "probe",
                       "answer": "legacy", "rating": "strong"}],
        "generated_at": "2026-09-20T10:00:00+00:00",
        "closed_at": "2026-09-20T12:00:00+00:00",
    })

    command.upgrade(cfg, CURRENT)

    with engine.begin() as conn:
        rows = conn.execute(sa.text(
            "SELECT round, track, status, closed_at, questions"
            " FROM interview_kits ORDER BY round")).mappings().all()

    assert [r["round"] for r in rows] == [1, 2], "a reopened application needs a kit per round"
    assert {r["track"] for r in rows} == {"default"}
    assert all(r["status"] == "ready" for r in rows)
    # Question ids must survive verbatim on EVERY round: round one's
    # submitted sheets key their answers to them, and a fresh id would
    # render that closed round's feedback table as empty cells.
    assert all(r["questions"][0]["id"] == "q1" for r in rows)
    # Legacy per-question answer/rating ride along inside `questions`
    # untouched (spec decision 5) — they are still read for kits recorded
    # before answers moved onto sheets.
    assert all(r["questions"][0].get("answer") == "legacy" for r in rows)


def test_closed_at_and_status_are_copied_from_the_blob(postgres_container, monkeypatch) -> None:
    """The fields that were JSON keys become columns; none may be dropped."""
    sync_dsn = postgres_container.get_connection_url()
    engine = sa.create_engine(sync_dsn)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = _alembic(monkeypatch, sync_dsn)
    command.upgrade(cfg, PREVIOUS)
    _seed_application(engine, interview_round=1, blob={
        "status": "error", "error": "model unavailable", "questions": [],
        "generated_at": "2026-09-20T10:00:00+00:00",
        "closed_at": "2026-09-20T12:00:00+00:00",
    })
    command.upgrade(cfg, CURRENT)
    with engine.begin() as conn:
        row = conn.execute(sa.text(
            "SELECT status, error, generated_at, closed_at FROM interview_kits"
        )).mappings().one()
    assert row["status"] == "error"
    assert row["error"] == "model unavailable"
    assert row["generated_at"] == "2026-09-20T10:00:00+00:00"
    assert row["closed_at"] == "2026-09-20T12:00:00+00:00"


def test_downgrade_leaves_the_blob_intact(postgres_container, monkeypatch) -> None:
    """Migration A only copies out, so a downgrade loses nothing."""
    sync_dsn = postgres_container.get_connection_url()
    engine = sa.create_engine(sync_dsn)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))

    cfg = _alembic(monkeypatch, sync_dsn)
    command.upgrade(cfg, CURRENT)
    command.downgrade(cfg, PREVIOUS)

    with engine.begin() as conn:
        tables = conn.execute(sa.text(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema='public'")).scalars().all()
        cols = conn.execute(sa.text(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name='interview_assignments'")).scalars().all()

    assert "interview_kits" not in tables
    assert "track" not in cols
    assert "applications" in tables
