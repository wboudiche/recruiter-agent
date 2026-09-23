"""Migration A against real Postgres.

The rest of the suite builds its schema with `Base.metadata.create_all`,
so migrations are otherwise never executed by a test. The per-round copy
is the part worth pinning: getting it wrong silently empties a closed
round's feedback table.
"""
import json

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from recruiter.config import get_config

PREVIOUS = "b8f3d1a20c47"   # the rounds migration
CURRENT = "c1a7e05b3f92"    # migration A
LATEST = "d4b8c1f60a37"     # migration B: drops applications.interview_kit
TEMPLATES = "e6f2a9c4b1d3"  # migration C: interview templates
TRACKS = "f3b7d2e8a915"     # migration D: interview tracks


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
        "submitted_at": "2026-09-20T11:00:00+00:00",
    })
    command.upgrade(cfg, CURRENT)
    with engine.begin() as conn:
        row = conn.execute(sa.text(
            "SELECT status, error, generated_at, closed_at, submitted_at FROM interview_kits"
        )).mappings().one()
    assert row["status"] == "error"
    assert row["error"] == "model unavailable"
    assert row["generated_at"] == "2026-09-20T10:00:00+00:00"
    assert row["closed_at"] == "2026-09-20T12:00:00+00:00"
    # Legacy single-submit timestamp: still read by any pre-multi-interviewer
    # kit, so it must round-trip like every other blob field.
    assert row["submitted_at"] == "2026-09-20T11:00:00+00:00"


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


def test_dropping_the_blob_and_rebuilding_it(postgres_container, monkeypatch) -> None:
    """Migration B's downgrade rebuilds the blob with `json_build_object`
    against the `interview_kits` table. That rebuild only ever runs on an
    empty database unless a row exists to rebuild from — seed one here so
    the data path actually executes, and check every field it copies."""
    sync_dsn = postgres_container.get_connection_url()
    engine = sa.create_engine(sync_dsn)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))

    cfg = _alembic(monkeypatch, sync_dsn)
    command.upgrade(cfg, PREVIOUS)
    _seed_application(engine, interview_round=1, blob={
        "status": "error",
        "error": "model unavailable",
        "generated_at": "2026-09-20T10:00:00+00:00",
        "generating_since": "2026-09-20T09:55:00+00:00",
        "submitted_at": "2026-09-20T11:00:00+00:00",
        "closed_at": "2026-09-20T12:00:00+00:00",
        "questions": [{"id": "q1", "text": "Why?", "source": "probe",
                       "answer": "legacy", "rating": "strong"}],
    })

    command.upgrade(cfg, LATEST)
    with engine.begin() as conn:
        cols = conn.execute(sa.text(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name='applications'")).scalars().all()
    assert "interview_kit" not in cols

    command.downgrade(cfg, CURRENT)
    with engine.begin() as conn:
        cols = conn.execute(sa.text(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name='applications'")).scalars().all()
        blob = conn.execute(sa.text(
            "SELECT interview_kit FROM applications")).scalars().one()

    assert "interview_kit" in cols
    assert blob["status"] == "error"
    assert blob["error"] == "model unavailable"
    assert blob["generated_at"] == "2026-09-20T10:00:00+00:00"
    assert blob["generating_since"] == "2026-09-20T09:55:00+00:00"
    assert blob["submitted_at"] == "2026-09-20T11:00:00+00:00"
    assert blob["closed_at"] == "2026-09-20T12:00:00+00:00"
    assert blob["questions"][0]["id"] == "q1"
    # Legacy per-question answer/rating must survive the round trip nested
    # inside `questions`, not just the seven top-level kit fields.
    assert blob["questions"][0]["answer"] == "legacy"
    assert blob["questions"][0]["rating"] == "strong"


def test_templates_migration_is_additive_and_reversible(postgres_container,
                                                        monkeypatch) -> None:
    """Existing kits must come through with no template — the "nothing
    changes until someone creates a template" guarantee — and the
    downgrade must leave them intact."""
    sync_dsn = postgres_container.get_connection_url()
    engine = sa.create_engine(sync_dsn)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))

    cfg = _alembic(monkeypatch, sync_dsn)
    command.upgrade(cfg, LATEST)
    with engine.begin() as conn:
        conn.execute(sa.text(
            "INSERT INTO jobs (title, description, criteria, status, created_at,"
            " updated_at) VALUES ('J','d','[]','open',now(),now())"))
        conn.execute(sa.text(
            "INSERT INTO candidates (source_type, full_name, skills, experience,"
            " education, links, created_at, updated_at)"
            " VALUES ('paste','C','[]','[]','[]','[]',now(),now())"))
        conn.execute(sa.text(
            "INSERT INTO applications (job_id, candidate_id, stage,"
            " interview_round, created_at, updated_at)"
            " SELECT (SELECT id FROM jobs LIMIT 1),"
            " (SELECT id FROM candidates LIMIT 1),"
            " 'scheduled', 1, now(), now()"))
        conn.execute(sa.text(
            "INSERT INTO interview_kits (application_id, round, track,"
            " questions, status, created_at, updated_at)"
            " SELECT id, 1, 'default',"
            " '[{\"id\":\"b1\",\"text\":\"Why?\",\"source\":\"baseline\"}]',"
            " 'ready', now(), now() FROM applications LIMIT 1"))

    command.upgrade(cfg, TEMPLATES)
    with engine.begin() as conn:
        kit = conn.execute(sa.text(
            "SELECT template_id, template_name, template_snapshot, questions"
            " FROM interview_kits")).mappings().one()
        job_default = conn.execute(sa.text(
            "SELECT default_interview_template_id FROM jobs")).scalar_one()
        # The partial unique index: two ACTIVE templates may not share a
        # name, but an archived one does not block the name.
        conn.execute(sa.text(
            "INSERT INTO interview_templates (name, questions)"
            " VALUES ('RH screen', '[]')"))
        conn.execute(sa.text(
            "UPDATE interview_templates SET is_active = false"
            " WHERE name = 'RH screen'"))
        conn.execute(sa.text(
            "INSERT INTO interview_templates (name, questions)"
            " VALUES ('RH screen', '[]')"))

    assert (kit["template_id"], kit["template_name"],
            kit["template_snapshot"]) == (None, None, None)
    assert kit["questions"][0]["id"] == "b1"
    assert job_default is None

    command.downgrade(cfg, LATEST)
    with engine.begin() as conn:
        tables = conn.execute(sa.text(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema='public'")).scalars().all()
        kit_count = conn.execute(sa.text(
            "SELECT count(*) FROM interview_kits")).scalar_one()
    assert "interview_templates" not in tables
    assert kit_count == 1, "downgrading the templates migration lost a kit"

    # And back up again: the downgrade must leave nothing behind that
    # blocks re-applying the migration.
    command.upgrade(cfg, TEMPLATES)
    with engine.begin() as conn:
        assert conn.execute(sa.text(
            "SELECT count(*) FROM interview_templates")).scalar_one() == 0


def test_tracks_migration_rekeys_templated_kits_and_is_reversible(
    postgres_container, monkeypatch,
) -> None:
    """A phase-2 kit built from a template is re-keyed to t<template_id>
    with its panel; a plain kit stays `default`; one person cannot sit on
    two tracks of a round; the downgrade refuses once a round has two."""
    sync_dsn = postgres_container.get_connection_url()
    engine = sa.create_engine(sync_dsn)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))

    cfg = _alembic(monkeypatch, sync_dsn)
    command.upgrade(cfg, TEMPLATES)
    with engine.begin() as conn:
        tid = conn.execute(sa.text(
            "INSERT INTO interview_templates (name, questions) VALUES ('RH screen', '[]')"
            " RETURNING id")).scalar_one()
        conn.execute(sa.text(
            "INSERT INTO jobs (title, description, criteria, status, created_at, updated_at)"
            " VALUES ('J','d','[]','open',now(),now())"))
        conn.execute(sa.text(
            "INSERT INTO candidates (source_type, full_name, skills, experience, education,"
            " links, created_at, updated_at)"
            " VALUES ('paste','C1','[]','[]','[]','[]',now(),now())"))
        conn.execute(sa.text(
            "INSERT INTO candidates (source_type, full_name, skills, experience, education,"
            " links, created_at, updated_at)"
            " VALUES ('paste','C2','[]','[]','[]','[]',now(),now())"))
        user_id = conn.execute(sa.text(
            "INSERT INTO users (email, role, is_active, created_at, updated_at)"
            " VALUES ('i@acme.com', 'viewer', true, now(), now()) RETURNING id")).scalar_one()
        app_ids = [conn.execute(sa.text(
            "INSERT INTO applications (job_id, candidate_id, stage, interview_round,"
            " created_at, updated_at)"
            " VALUES ((SELECT id FROM jobs LIMIT 1),"
            " (SELECT id FROM candidates LIMIT 1 OFFSET :offset),"
            " 'scheduled', 1, now(), now()) RETURNING id"),
            {"offset": i}).scalar_one() for i in range(2)]
        templated, plain = app_ids
        for app_id, template_id in ((templated, tid), (plain, None)):
            conn.execute(sa.text(
                "INSERT INTO interview_kits (application_id, round, track, questions, status,"
                " template_id, created_at, updated_at)"
                " VALUES (:a, 1, 'default', '[]', 'ready', :t, now(), now())"),
                {"a": app_id, "t": template_id})
            conn.execute(sa.text(
                "INSERT INTO interview_assignments (application_id, user_id, round, track,"
                " sheet, created_at, updated_at)"
                " VALUES (:a, :u, 1, 'default', '{}', now(), now())"),
                {"a": app_id, "u": user_id})

    command.upgrade(cfg, TRACKS)
    with engine.begin() as conn:
        kits = dict(conn.execute(sa.text(
            "SELECT application_id, track FROM interview_kits")).all())
        panel = dict(conn.execute(sa.text(
            "SELECT application_id, track FROM interview_assignments")).all())
        with pytest.raises(sa.exc.IntegrityError), conn.begin_nested():
            conn.execute(sa.text(
                "INSERT INTO interview_assignments (application_id, user_id, round, track,"
                " sheet, created_at, updated_at)"
                " VALUES (:a, :u, 1, 'other', '{}', now(), now())"),
                {"a": plain, "u": user_id})
        conn.execute(sa.text(
            "INSERT INTO interview_kits (application_id, round, track, questions, status,"
            " created_at, updated_at) VALUES (:a, 1, 'extra', '[]', 'ready', now(), now())"),
            {"a": templated})

    assert kits == {templated: f"t{tid}", plain: "default"}
    assert panel == {templated: f"t{tid}", plain: "default"}

    with pytest.raises(RuntimeError, match="more than one interview track"):
        command.downgrade(cfg, TEMPLATES)

    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM interview_kits WHERE track = 'extra'"))
    command.downgrade(cfg, TEMPLATES)
    with engine.begin() as conn:
        kit_tracks = set(conn.execute(sa.text("SELECT track FROM interview_kits")).scalars())
        row_tracks = set(conn.execute(sa.text(
            "SELECT track FROM interview_assignments")).scalars())
    assert kit_tracks == row_tracks == {"default"}

    command.upgrade(cfg, TRACKS)
