# Interview Kits As Rows — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move interview kits out of the `applications.interview_kit` JSON blob into an `interview_kits` table keyed by `(application_id, round, track)`, with no user-visible behaviour change except that round two can regenerate its questions again.

**Architecture:** Two migrations bracket the refactor. Migration A creates the table, backfills one row per round, and adds `track` to `interview_assignments` — the blob stays untouched so the tree is green at every commit. The call sites then switch to the table through one small store module. Migration B drops the blob last, once nothing reads it.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Postgres 16, pytest + pytest-asyncio, testcontainers.

**Spec:** `docs/superpowers/specs/2026-09-20-interview-kits-as-rows-design.md`

## Global Constraints

- **The existing kit, freeze, sheet, panel and rounds tests must pass unchanged.** Task 2 is a pure refactor; any test whose expectations move is a behaviour change and must be called out, not quietly adjusted. Only Task 3 is allowed to change an existing test, and only the ones named there.
- **ORM model is `InterviewKitRow`.** `InterviewKit` is already the Pydantic schema in `src/recruiter/schemas/interview.py`, imported by `src/recruiter/api/interview.py` — the module that also imports the model. Spec decision 7.
- **`track` is always the string `"default"` in this phase.** It lands now because it is part of the unique constraint. Spec decision 2.
- **Run the whole backend suite before every commit:** `uv run pytest -q`. It takes about 3 minutes.
- **Ruff baseline is 461 findings** (`uv run ruff check src/ tests/`). Ruff is not in CI; do not increase the number. Alembic files match the generated header of their siblings and are expected to carry `UP035` + `I001`.
- **Commit messages** end with:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

---

## File Structure

**Created**
- `src/recruiter/models/interview_kit_row.py` — the ORM row. One responsibility: the table definition.
- `src/recruiter/pipeline/kit_store.py` — reading, creating and converting kit rows. No FastAPI imports, so both routers can use it without a cycle.
- `alembic/versions/20260921_000000_interview_kits_table.py` — migration A.
- `alembic/versions/20260922_000000_drop_application_interview_kit.py` — migration B.
- `tests/api/test_kit_migration.py` — migration round-trip against real Postgres.
- `tests/unit/test_kit_store.py` — the store's pure conversions.

**Modified**
- `src/recruiter/models/__init__.py` — register the model.
- `src/recruiter/models/interview_assignment.py` — add `track`, widen the unique constraint.
- `src/recruiter/models/application.py` — drop the blob field (Task 4 only).
- `src/recruiter/api/interview.py` — 14 blob references.
- `src/recruiter/api/applications.py` — 8 blob references.
- `src/recruiter/pipeline/interview_sheets.py` — 3 blob references.

---

### Task 1: The table, the model, and migration A

**Files:**
- Create: `src/recruiter/models/interview_kit_row.py`
- Create: `alembic/versions/20260921_000000_interview_kits_table.py`
- Create: `tests/api/test_kit_migration.py`
- Modify: `src/recruiter/models/__init__.py`
- Modify: `src/recruiter/models/interview_assignment.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `InterviewKitRow` with columns `id, application_id, round, track, questions, status, error, generated_at, generating_since, closed_at, created_at, updated_at`; `InterviewAssignment.track: str`.

- [ ] **Step 1: Write the model**

Create `src/recruiter/models/interview_kit_row.py`:

```python
from datetime import datetime

from sqlalchemy import (
    JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


class InterviewKitRow(Base):
    """One question list, for one round and one track of one application.

    Named with a Row suffix on purpose: `InterviewKit` is the Pydantic
    schema in schemas/interview.py, and api/interview.py imports both.

    Sheets live on `interview_assignments` and are matched to their kit by
    (application_id, round, track) — a sheet's answers are keyed by the
    question ids in `questions`, so the two must always be read as a pair.
    """

    __tablename__ = "interview_kits"
    __table_args__ = (
        UniqueConstraint("application_id", "round", "track",
                         name="uq_interview_kit_app_round_track"),
        Index("ix_interview_kits_application_id", "application_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False,
    )
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # Always "default" in phase 1; parallel tracks are phase 3. It is on the
    # unique constraint, so adding it later would rebuild that twice.
    track: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default", server_default="default",
    )
    questions: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready")
    error: Mapped[str | None] = mapped_column(String)
    # ISO-8601 strings, matching the Pydantic schema these mirror.
    generated_at: Mapped[str | None] = mapped_column(String)
    generating_since: Mapped[str | None] = mapped_column(String)
    closed_at: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
```

- [ ] **Step 2: Register the model**

In `src/recruiter/models/__init__.py`, add the import next to `InterviewAssignment` (alphabetical — ruff enforces `I001`):

```python
from recruiter.models.interview_kit_row import InterviewKitRow
```

and add `"InterviewKitRow",` to `__all__` between `"InterviewAssignment",` and `"Job",`.

- [ ] **Step 3: Add `track` to assignments**

In `src/recruiter/models/interview_assignment.py`, add the column immediately after `round`:

```python
    # Which track within the round. Always "default" until phase 3; part of
    # the unique constraint below.
    track: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default", server_default="default",
    )
```

Add `String` to the `sqlalchemy` import line. Change the constraint to:

```python
        UniqueConstraint("application_id", "user_id", "round", "track",
                         name="uq_interview_assignment_app_user_round_track"),
```

- [ ] **Step 4: Write migration A**

Create `alembic/versions/20260921_000000_interview_kits_table.py`. `down_revision` is `b8f3d1a20c47` (the rounds migration — confirm with `uv run alembic heads`).

```python
"""move interview kits into their own table, keyed by (application, round, track)

Revision ID: c1a7e05b3f92
Revises: b8f3d1a20c47
Create Date: 2026-09-21 00:00:00.000000

The blob is left in place: this migration only copies out of it, so a
downgrade is lossless and the application keeps working at either
revision. Dropping applications.interview_kit is a separate migration
that runs once nothing reads it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c1a7e05b3f92'
down_revision: Union[str, None] = 'b8f3d1a20c47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "interview_kits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("application_id", sa.Integer(),
                  sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("track", sa.String(length=64), nullable=False, server_default="default"),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("generated_at", sa.String(), nullable=True),
        sa.Column("generating_since", sa.String(), nullable=True),
        sa.Column("closed_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("application_id", "round", "track",
                            name="uq_interview_kit_app_round_track"),
    )
    op.create_index("ix_interview_kits_application_id", "interview_kits", ["application_id"])

    op.add_column(
        "interview_assignments",
        sa.Column("track", sa.String(length=64), nullable=False, server_default="default"),
    )
    op.drop_constraint(
        "uq_interview_assignment_app_user_round", "interview_assignments", type_="unique",
    )
    op.create_unique_constraint(
        "uq_interview_assignment_app_user_round_track",
        "interview_assignments",
        ["application_id", "user_id", "round", "track"],
    )

    # One row per round from 1 to the application's current round, each a
    # copy. An application reopened into round 2 shares ONE kit today, and
    # round 1's submitted sheets resolve their answers against its question
    # ids — a single row at the live round would leave that feedback
    # pointing at a kit that does not exist.
    op.execute("""
        INSERT INTO interview_kits (
            application_id, round, track, questions, status, error,
            generated_at, generating_since, closed_at, created_at, updated_at
        )
        SELECT a.id,
               r.round,
               'default',
               COALESCE(a.interview_kit -> 'questions', '[]'::json),
               COALESCE(a.interview_kit ->> 'status', 'ready'),
               a.interview_kit ->> 'error',
               a.interview_kit ->> 'generated_at',
               a.interview_kit ->> 'generating_since',
               a.interview_kit ->> 'closed_at',
               now(), now()
        FROM applications a
        CROSS JOIN LATERAL generate_series(1, a.interview_round) AS r(round)
        WHERE a.interview_kit IS NOT NULL
    """)


def downgrade() -> None:
    # Lossless: applications.interview_kit was never touched.
    op.drop_constraint(
        "uq_interview_assignment_app_user_round_track", "interview_assignments", type_="unique",
    )
    op.create_unique_constraint(
        "uq_interview_assignment_app_user_round", "interview_assignments",
        ["application_id", "user_id", "round"],
    )
    op.drop_column("interview_assignments", "track")
    op.drop_index("ix_interview_kits_application_id", table_name="interview_kits")
    op.drop_table("interview_kits")
```

- [ ] **Step 5: Write the failing migration test**

Create `tests/api/test_kit_migration.py`. This is a **sync** test: `alembic/env.py` calls `asyncio.run`, which cannot nest inside an async test.

```python
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
```

- [ ] **Step 6: Run the migration test to verify it fails**

Run: `uv run pytest tests/api/test_kit_migration.py -q`
Expected: FAIL — `alembic.util.exc.CommandError: Can't locate revision identified by 'c1a7e05b3f92'` before Step 4 is saved, or a missing-table error if the revision exists but the steps above were skipped.

- [ ] **Step 7: Run the migration test to verify it passes**

Run: `uv run pytest tests/api/test_kit_migration.py -q`
Expected: PASS, 3 tests.

- [ ] **Step 8: Confirm a single alembic head and the full suite**

Run: `uv run alembic heads` — expected: exactly one line, `c1a7e05b3f92 (head)`.
Run: `uv run pytest -q` — expected: all pass. Nothing reads the new table yet, so the count only rises by the 2 new tests.

- [ ] **Step 9: Commit**

```bash
git add src/recruiter/models tests/api/test_kit_migration.py alembic/versions
git commit -m "feat(interview-kit): add the interview_kits table and backfill it

One row per (application, round, track), backfilled with a copy per round
because a reopened application shares one blob today and round one's
submitted sheets resolve against its question ids.

The blob is deliberately left in place so this revision is lossless in
both directions and nothing has to change at once.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The store, and switching every call site

**Files:**
- Create: `src/recruiter/pipeline/kit_store.py`
- Create: `tests/unit/test_kit_store.py`
- Modify: `src/recruiter/api/interview.py`
- Modify: `src/recruiter/api/applications.py`
- Modify: `src/recruiter/pipeline/interview_sheets.py`

**Interfaces:**
- Consumes: `InterviewKitRow` from Task 1.
- Produces:
  - `async kit_for(session, app_row, *, track="default") -> InterviewKitRow | None`
  - `async create_kit(session, app_row, *, round: int, track="default", questions=None, status="ready") -> InterviewKitRow`
  - `content_of(row: InterviewKitRow) -> InterviewKit`
  - `apply_content(row: InterviewKitRow, kit: InterviewKit) -> None`

- [ ] **Step 1: Write the failing store test**

Create `tests/unit/test_kit_store.py`:

```python
from recruiter.models.interview_kit_row import InterviewKitRow
from recruiter.pipeline.kit_store import apply_content, content_of
from recruiter.schemas.interview import InterviewKit, KitQuestion


def _row() -> InterviewKitRow:
    return InterviewKitRow(
        application_id=1, round=1, track="default", status="ready",
        error=None, generated_at="2026-09-20T10:00:00+00:00",
        generating_since=None, closed_at=None,
        questions=[{"id": "q1", "text": "Why?", "source": "probe"}],
    )


def test_content_of_reads_the_row_as_the_api_shape() -> None:
    kit = content_of(_row())
    assert kit.status == "ready"
    assert kit.generated_at == "2026-09-20T10:00:00+00:00"
    assert [q.id for q in kit.questions] == ["q1"]


def test_apply_content_writes_every_field_back() -> None:
    """A round trip must not silently drop a field — the row and the schema
    have to stay in step as either gains one."""
    row = _row()
    apply_content(row, InterviewKit(
        status="error", error="model unavailable",
        generated_at="2026-09-21T09:00:00+00:00",
        generating_since="2026-09-21T08:59:00+00:00",
        closed_at="2026-09-21T10:00:00+00:00",
        questions=[KitQuestion(id="q2", text="How?", source="baseline")],
    ))
    assert row.status == "error"
    assert row.error == "model unavailable"
    assert row.generated_at == "2026-09-21T09:00:00+00:00"
    assert row.generating_since == "2026-09-21T08:59:00+00:00"
    assert row.closed_at == "2026-09-21T10:00:00+00:00"
    assert [q["id"] for q in row.questions] == ["q2"]


def test_round_trip_is_lossless() -> None:
    row = _row()
    apply_content(row, content_of(row))
    assert content_of(row).model_dump() == content_of(_row()).model_dump()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_kit_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'recruiter.pipeline.kit_store'`.

- [ ] **Step 3: Write the store**

Create `src/recruiter/pipeline/kit_store.py`:

```python
"""Reading, creating and converting interview kit rows.

Kept out of the routers so both `api/interview.py` and
`api/applications.py` can use it without importing each other — the same
cycle `interview_sheets.py` already works around.

The Pydantic `InterviewKit` stays the API shape; these two converters are
the only place the row and the schema meet.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.models import Application
from recruiter.models.interview_kit_row import InterviewKitRow
from recruiter.schemas.interview import InterviewKit

DEFAULT_TRACK = "default"


async def kit_for(
    session: AsyncSession, app_row: Application, *, track: str = DEFAULT_TRACK,
) -> InterviewKitRow | None:
    """The kit for the application's CURRENT round. Reads only — creation is
    explicit at the three points that mean it (entering scheduled, opening
    the next round, and generating on an application that has none yet)."""
    return (await session.execute(
        select(InterviewKitRow).where(
            InterviewKitRow.application_id == app_row.id,
            InterviewKitRow.round == app_row.interview_round,
            InterviewKitRow.track == track,
        )
    )).scalars().one_or_none()


async def create_kit(
    session: AsyncSession,
    app_row: Application,
    *,
    round: int,
    track: str = DEFAULT_TRACK,
    questions: list[dict] | None = None,
    status: str = "ready",
) -> InterviewKitRow:
    row = InterviewKitRow(
        application_id=app_row.id, round=round, track=track,
        questions=questions or [], status=status,
    )
    session.add(row)
    await session.flush()
    return row


def content_of(row: InterviewKitRow) -> InterviewKit:
    return InterviewKit.model_validate({
        "status": row.status,
        "error": row.error,
        "generated_at": row.generated_at,
        "generating_since": row.generating_since,
        "closed_at": row.closed_at,
        "questions": row.questions or [],
    })


def apply_content(row: InterviewKitRow, kit: InterviewKit) -> None:
    row.status = kit.status
    row.error = kit.error
    row.generated_at = kit.generated_at
    row.generating_since = kit.generating_since
    row.closed_at = kit.closed_at
    row.questions = [q.model_dump() for q in kit.questions]
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/unit/test_kit_store.py -q`
Expected: PASS, 3 tests.

- [ ] **Step 5: Switch `pipeline/interview_sheets.py`**

`mark_interviewed` currently writes the blob. Change its signature to take the row and stop touching `app_row.interview_kit`:

```python
def mark_interviewed(
    app_row: Application, kit_row: InterviewKitRow, now: datetime,
) -> None:
    """Close the round: move the application to INTERVIEWED and stamp the
    kit's closed_at. Shared by the automatic all-sheets-in rule
    (close_round_if_complete) and the recruiter's manual override in
    patch_application, so both paths stamp the same fields the same way."""
    app_row.stage = Stage.INTERVIEWED
    app_row.interviewed_at = now
    kit_row.closed_at = now.isoformat()
```

In `close_round_if_complete`, replace the blob guard and the final call:

```python
    from recruiter.api.interviewers import load_assignments
    from recruiter.pipeline.kit_store import kit_for

    if app_row.stage != Stage.SCHEDULED:
        return False
    kit_row = await kit_for(session, app_row)
    if kit_row is None:
        return False
    rows = rows_in_round(
        await load_assignments(session, app_row.id), app_row.interview_round,
    )
    if not all_submitted(rows):
        return False
    mark_interviewed(app_row, kit_row, datetime.now(UTC))
    return True
```

Remove the now-unused `InterviewKit` import if nothing else in the module uses it.

- [ ] **Step 6: Switch `api/interview.py`**

Replace each blob access with the row. The seven sites and their replacements:

1. `_read` (~line 85): `raw = app_row.interview_kit` becomes
   ```python
   row = await kit_for(session, app_row)
   return InterviewKitRead(
       kit=content_of(row) if row else None,
       sheets=await _sheets_for(session, app_row, user),
   )
   ```
   `_read` already takes `session`.
2. `run_generate_kit` (~line 117): `existing_raw = app_row.interview_kit or {}` becomes
   ```python
   kit_row = await kit_for(session, app_row)
   existing_raw = content_of(kit_row).model_dump() if kit_row else {}
   ```
3. `run_generate_kit` final write (~line 187): `app_row.interview_kit = kit.model_dump()` becomes
   ```python
   if kit_row is None:
       kit_row = await create_kit(session, app_row, round=app_row.interview_round)
   apply_content(kit_row, kit)
   ```
4. `generate_kit` (~line 208): `existing = app_row.interview_kit or {}` becomes the same
   `kit_row` / `content_of` pair as (2).
5. `generate_kit` stuck-kit recovery (~line 221) and the generating stamp (~line 233): mutate
   `kit_row` fields directly — `kit_row.status = "ready"`, `kit_row.error = None`,
   `kit_row.generating_since = _now()` — instead of rebuilding a dict. When `kit_row is None`,
   create it first with `create_kit(...)`, which is how the "Generate interview kit" button
   works from a standing start (spec decision 8).
6. `patch_kit` (~lines 259–323): `_require_kit(app_row)` becomes `_require_kit(kit_row)`; the
   final `app_row.interview_kit = kit.model_dump()` becomes `apply_content(kit_row, kit)`.
7. `draft_kit_question` (~line 468): `(app_row.interview_kit or {}).get("questions")` becomes
   `(kit_row.questions if kit_row else [])`.

Change `_require_kit` to take the row:

```python
def _require_kit(kit_row: InterviewKitRow | None) -> InterviewKit:
    if kit_row is None:
        raise HTTPException(status_code=404, detail="no interview kit; generate one first")
    return content_of(kit_row)
```

Add the import, alphabetically before `interview_kit`:

```python
from recruiter.pipeline.kit_store import apply_content, content_of, create_kit, kit_for
```

Leave the SSE payload `{"type": "interview_kit", ...}` alone — that is an event name, not the column.

- [ ] **Step 7: Switch `api/applications.py`**

1. `_open_next_round` (~line 371): replace the `closed_at` clear with creating the next round's
   row as a copy of the one just closed:
   ```python
       previous_kit = await kit_for(session, app_row)   # still the old round here
       ...
       app_row.interview_round = previous_round + 1
       app_row.interviewed_at = None
       if previous_kit is not None:
           await create_kit(
               session, app_row,
               round=app_row.interview_round,
               questions=list(previous_kit.questions or []),
               status="ready",
           )
   ```
   Read `previous_kit` **before** bumping `interview_round`, because `kit_for` keys on it.
2. Entering `scheduled` (~lines 419–443): `existing = app_row.interview_kit or {}` becomes
   `kit_row = await kit_for(session, app_row)`; the "recover a stuck kit" branch sets
   `kit_row.status = "ready"; kit_row.error = None`; the "mark generating" branch creates the
   row when absent and then sets `status`/`error`/`generating_since` on it.
3. `Stage.INTERVIEWED` (~line 453): `mark_interviewed(app_row, InterviewKit.model_validate(...))`
   becomes
   ```python
           kit_row = await kit_for(session, app_row)
           if kit_row is not None:
               mark_interviewed(app_row, kit_row, now)
           else:
               app_row.interviewed_at = now
   ```
4. `_to_read` / any remaining blob read (~line 492): drop it; the kit is not part of
   `ApplicationRead`.

Add `from recruiter.pipeline.kit_store import create_kit, kit_for` and drop the
`InterviewKit` schema import if unused.

- [ ] **Step 8: Write the kit-lifecycle tests**

The spec asks for these three explicitly; without them the row's creation
points are only covered indirectly. Add to `tests/api/test_interview_rounds.py`:

```python
async def _kit_rows(app_id: int) -> list[InterviewKitRow]:
    SessionLocal = await _sessionmaker()
    async with SessionLocal() as session:
        return list((await session.execute(
            select(InterviewKitRow)
            .where(InterviewKitRow.application_id == app_id)
            .order_by(InterviewKitRow.round)
        )).scalars().all())


@pytest.mark.asyncio
async def test_entering_scheduled_creates_a_kit_row(
    api_client: AsyncClient, create_scored_app,
) -> None:
    app.dependency_overrides[get_llm] = _fake_llm
    try:
        app_id = await create_scored_app()
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
        SessionLocal = await _sessionmaker()
        async with SessionLocal() as session:
            await session.execute(
                update(Application).where(Application.id == app_id).values(stage=Stage.INVITED))
            await session.commit()

        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})

        rows = await _kit_rows(app_id)
        assert [(r.round, r.track) for r in rows] == [(1, "default")]
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_reopening_creates_the_next_rounds_kit_rather_than_mutating_the_first(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """Round one's row must survive untouched — its closed_at is the record
    that the round happened, and its questions anchor round one's answers."""
    app.dependency_overrides[get_llm] = _fake_llm
    try:
        app_id = await create_scored_app()
        await _interviewed_with_panel(api_client, app_id)
        before = await _kit_rows(app_id)
        assert len(before) == 1 and before[0].closed_at is not None
        first_questions = list(before[0].questions)

        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})

        rows = await _kit_rows(app_id)
        assert [r.round for r in rows] == [1, 2]
        assert rows[0].closed_at is not None, "round one was reopened instead of round two"
        assert rows[1].closed_at is None
        assert [q["id"] for q in rows[1].questions] == [q["id"] for q in first_questions]
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_generate_creates_a_kit_when_the_application_has_none(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """The "Generate interview kit" button works from a standing start, so
    generate must create the row rather than 404 on a missing one."""
    app_id = await create_scored_app()
    llm = _fake_llm()
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        resp = await api_client.post(f"/api/applications/{app_id}/interview-kit/generate")
        assert resp.status_code == 202, resp.text
    finally:
        app.dependency_overrides.pop(get_llm, None)

    rows = await _kit_rows(app_id)
    assert [(r.round, r.track) for r in rows] == [(1, "default")]
    assert rows[0].questions, "generation produced no questions"
```

Add `from recruiter.models.interview_kit_row import InterviewKitRow` and `select` to that
file's imports.

- [ ] **Step 9: Run them**

Run: `uv run pytest tests/api/test_interview_rounds.py -q`
Expected: PASS.

- [ ] **Step 10: Run the whole suite — nothing should have moved**

Run: `uv run pytest -q`
Expected: PASS at the same count as Task 1 plus the 3 store tests and the 3 lifecycle tests.
**If any pre-existing test fails, do not edit it** — the refactor changed behaviour somewhere.
Find the behaviour difference and fix the code.

Two of those pre-existing tests carry a specific meaning here. The spec asks that
`generation_in_flight` now read the row's `generating_since` rather than a JSON key; the
signal that it does is that `test_a_second_generate_while_one_is_running_is_a_no_op` and
`test_a_generate_after_a_stale_run_is_allowed` (both in
`tests/api/test_interview_stage_wiring.py`) still pass. Check them by name:

Run: `uv run pytest tests/api/test_interview_stage_wiring.py -q -k "no_op or stale_run"`
Expected: PASS, 2 tests.

- [ ] **Step 11: Check lint and types**

Run: `uv run ruff check src/ tests/` — expected: `Found 461 errors` or fewer.
Run: `uv run mypy src/recruiter/pipeline/kit_store.py src/recruiter/models/interview_kit_row.py` — expected: `Success`.

- [ ] **Step 12: Commit**

```bash
git add src/recruiter tests
git commit -m "refactor(interview-kit): read and write kits through the table

Every call site moves from applications.interview_kit to the row for
(application, current round, 'default'), behind one small store module
that both routers can import without a cycle.

No behaviour change: the existing kit, freeze, sheet, panel and rounds
tests pass untouched, which is this commit's correctness signal.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The freeze becomes per-kit

**Files:**
- Modify: `src/recruiter/pipeline/interview_sheets.py`
- Modify: `src/recruiter/api/interview.py`
- Modify: `tests/unit/test_interview_sheets_rules.py`
- Modify: `tests/api/test_interview_rounds.py`

**Interfaces:**
- Consumes: `kit_for` from Task 2.
- Produces: `is_frozen` scoped to one round's rows; no new signatures.

This is the one task allowed to change existing tests, and only the two named below.

- [ ] **Step 1: Write the failing test for round-two regeneration**

In `tests/api/test_interview_rounds.py`, add:

```python
@pytest.mark.asyncio
async def test_a_reopened_round_can_regenerate_its_questions(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """Round one's answers are keyed to round one's kit, so regenerating
    round two cannot orphan them. Before kits were rows the freeze had to
    span every round, which left a reopened round permanently stuck with
    the questions it inherited."""
    app.dependency_overrides[get_llm] = _fake_llm
    try:
        app_id = await create_scored_app()
        await _interviewed_with_panel(api_client, app_id)
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})

        resp = await api_client.post(f"/api/applications/{app_id}/interview-kit/generate")

        assert resp.status_code == 202, resp.text
        kit = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()["kit"]
        assert kit["status"] == "ready"
    finally:
        app.dependency_overrides.pop(get_llm, None)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/api/test_interview_rounds.py -q -k regenerate`
Expected: FAIL — `assert 409 == 202`, detail `questions are frozen: a sheet has been submitted`.

- [ ] **Step 3: Scope the freeze to the round**

In `src/recruiter/pipeline/interview_sheets.py`, rewrite the docstring and leave the body as-is — the change is that **callers now pass one round's rows**:

```python
def is_frozen(rows: Iterable[InterviewAssignment]) -> bool:
    """Once any sheet is submitted the question list must not lose rows,
    or submitted feedback would silently lose its answers.

    Scoped to ONE kit's rows: callers pass `rows_in_round(...)`. Each round
    owns its questions now, so a regeneration in round two cannot orphan
    round one's answers — the reason this once had to span every round.
    """
    return any(r.submitted_at is not None for r in rows)
```

In `src/recruiter/api/interview.py`, every `is_frozen(rows)` becomes
`is_frozen(rows_in_round(rows, app_row.interview_round))` — three sites: `run_generate_kit`,
`generate_kit`, and `patch_kit`. Do the same at the one site in `api/applications.py`
(entering `scheduled`).

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/api/test_interview_rounds.py -q`
Expected: PASS, 5 tests.

- [ ] **Step 5: Update the two tests that pinned the global freeze**

In `tests/unit/test_interview_sheets_rules.py`, `test_the_question_freeze_spans_every_round`
asserted the old rule. Replace it with:

```python
def test_the_question_freeze_is_scoped_to_one_round() -> None:
    """Each round owns its questions now, so round one's submitted sheet
    does not freeze round two. Callers pass one round's rows."""
    rows = [_row(1, True, 1), _row(2, False, 2)]
    assert is_frozen(rows_in_round(rows, 1))
    assert not is_frozen(rows_in_round(rows, 2))
```

In `tests/api/test_interview_rounds.py`, `test_questions_stay_frozen_into_the_next_round`
asserted that a round-one submit blocks a round-two edit. That is the limitation being
removed. Replace its body's final assertions with:

```python
        assert resp.status_code == 200, resp.text
```

and rename it to `test_round_two_questions_are_editable_after_round_one_closed`, updating the
docstring to say why.

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS. Exactly two pre-existing tests changed, both named above.

- [ ] **Step 7: Commit**

```bash
git add src/recruiter tests
git commit -m "feat(interview-kit): scope the question freeze to its own round

The freeze spanned every round only because rounds shared one question
list: regenerating round two would mint fresh ids and orphan round one's
submitted answers. Each round owns its kit now, so the special case goes
— and with it the limitation that a reopened round could never regenerate
its questions at all.

Two tests asserted the old rule and are replaced, not adjusted.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Drop the blob

**Files:**
- Create: `alembic/versions/20260922_000000_drop_application_interview_kit.py`
- Modify: `src/recruiter/models/application.py`
- Modify: `tests/api/test_kit_migration.py`

**Interfaces:**
- Consumes: migration A's revision id `c1a7e05b3f92`.
- Produces: `applications.interview_kit` no longer exists.

- [ ] **Step 1: Confirm nothing reads it**

Run: `grep -rn "interview_kit\b" src/ --include=*.py | grep -v interview_kit_generator | grep -v interview_kits | grep -v '"type": "interview_kit"'`
Expected: only `src/recruiter/models/application.py`. Anything else must be fixed before continuing.

- [ ] **Step 2: Write migration B**

```python
"""drop applications.interview_kit now that kits are rows

Revision ID: d4b8c1f60a37
Revises: c1a7e05b3f92
Create Date: 2026-09-22 00:00:00.000000

Split from the migration that created interview_kits so that revision is
lossless in both directions. Downgrading past THIS one rebuilds the blob
from the highest round's kit, which is lossy for an application whose
rounds have diverged — they cannot in phase 1, where every round is a
copy, but phase 3 must revisit this.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd4b8c1f60a37'
down_revision: Union[str, None] = 'c1a7e05b3f92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("applications", "interview_kit")


def downgrade() -> None:
    op.add_column("applications", sa.Column("interview_kit", sa.JSON(), nullable=True))
    op.execute("""
        UPDATE applications a
        SET interview_kit = k.blob
        FROM (
            SELECT DISTINCT ON (application_id) application_id,
                   json_build_object(
                       'status', status,
                       'error', error,
                       'generated_at', generated_at,
                       'generating_since', generating_since,
                       'closed_at', closed_at,
                       'questions', questions
                   ) AS blob
            FROM interview_kits
            ORDER BY application_id, round DESC
        ) k
        WHERE a.id = k.application_id
    """)
```

- [ ] **Step 3: Remove the model field**

In `src/recruiter/models/application.py`, delete the line:

```python
    interview_kit: Mapped[dict | None] = mapped_column(JSON)
```

Keep the `JSON` import — `score_breakdown` and `enrichment` still use it.

- [ ] **Step 4: Extend the migration test**

In `tests/api/test_kit_migration.py`, add `LATEST = "d4b8c1f60a37"` and:

```python
def test_dropping_the_blob_and_rebuilding_it(postgres_container, monkeypatch) -> None:
    sync_dsn = postgres_container.get_connection_url()
    engine = sa.create_engine(sync_dsn)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))

    cfg = _alembic(monkeypatch, sync_dsn)
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
    assert "interview_kit" in cols
```

- [ ] **Step 5: Run the migration tests**

Run: `uv run pytest tests/api/test_kit_migration.py -q`
Expected: PASS, 3 tests.

- [ ] **Step 6: Run the whole suite and the baselines**

Run: `uv run pytest -q` — expected: all pass.
Run: `uv run alembic heads` — expected: one head, `d4b8c1f60a37 (head)`.
Run: `uv run ruff check src/ tests/` — expected: at most `Found 465 errors` (461 plus the two generated-header findings each new migration carries).
Run: `cd recruiter-frontend && npx vitest --run && npm run lint` — expected: unchanged; this phase touches no frontend.

- [ ] **Step 7: Verify the migration chain against a scratch Postgres**

The suite builds its schema with `create_all`, so this is the only check that the full chain
applies to a real database from empty:

```bash
docker run -d --rm --name kit-mig -e POSTGRES_PASSWORD=x -e POSTGRES_USER=recruiter \
  -e POSTGRES_DB=recruiter -p 55432:5432 postgres:16
until docker exec kit-mig pg_isready -U recruiter -d recruiter; do sleep 1; done
export RECRUITER_DATABASE_URL="postgresql+asyncpg://recruiter:x@localhost:55432/recruiter"
export RECRUITER_DEFAULT_ACCOUNT_EMAIL="mig@example.com"
export RECRUITER_DEFAULT_ACCOUNT_PASSWORD="migration-check-only"
export RECRUITER_SETTINGS_KEY="$(python3 -c 'import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')"
uv run alembic upgrade head && uv run alembic downgrade -2 && uv run alembic upgrade head
docker stop kit-mig
```

Expected: all three commands succeed with no error.

- [ ] **Step 8: Commit**

```bash
git add src/recruiter/models/application.py alembic/versions tests/api/test_kit_migration.py
git commit -m "refactor(interview-kit): drop applications.interview_kit

Nothing reads the blob now. Split from the migration that created
interview_kits so that one stays lossless in both directions; this one's
downgrade rebuilds the blob from the highest round, which phase 3 must
revisit once rounds can genuinely diverge.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```
