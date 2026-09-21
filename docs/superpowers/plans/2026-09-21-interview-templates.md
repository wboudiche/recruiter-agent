# Interview Templates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Org-wide interview templates that decide what a round's kit contains and whether it gets generated probes, chosen when a round starts — so round one can be technical and round two an RH screen.

**Architecture:** A new `interview_templates` table, a nullable default on `jobs`, and three snapshot columns on `interview_kits`. Two pure functions decide a kit's fixed questions and whether it gets probes from the kit's snapshot, never the live template. The round-start PATCH resolves which template applies; generation reads the snapshot. The frontend adds a Settings tab, a job-default select, and a picker that only appears once a template exists.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Postgres 16, pytest; React 18, TanStack Query, Radix UI, Vitest + Testing Library + msw.

**Spec:** `docs/superpowers/specs/2026-09-21-interview-templates-design.md`

## Global Constraints

- **With zero templates defined, nothing changes.** Every pre-existing backend and frontend test must pass. Pre-existing test files may change only where Task 6 says so. Two frontend test harnesses must learn about the new `GET /api/interview-templates` call: `action-bar.test.tsx` gets its api mock and its lookup of which call is the PATCH, and `application-detail.test.tsx` gets one msw handler. No expected value in any pre-existing test may change.
- Names, exactly: ORM model `InterviewTemplate` (`src/recruiter/models/interview_template.py`); schemas `TemplateQuestion`, `InterviewTemplateCreate`, `InterviewTemplateUpdate`, `InterviewTemplateRead`, `TemplateSnapshot`, and the literal type `ProbeMode` (`src/recruiter/schemas/interview_template.py`).
- `probe_mode` values are exactly `"score_gaps"` and `"none"`.
- A snapshotted template question id is exactly `f"t{template_id}-{question_id}"`. Job baseline ids are never rewritten.
- Template question ids are capped at **48** characters (`TEMPLATE_QUESTION_ID_MAX = 48`), so a namespaced id fits `KitQuestion.id`'s 64-character limit.
- `template_name` is exposed on `InterviewKitRead`, **not** on the `InterviewKit` content schema. `apply_content` writes every `InterviewKit` field back to the row, and `build_kit`/`merge_regenerated` build fresh `InterviewKit` objects, so a field there would be wiped to `None` on every regeneration.
- New routers are registered with `_api_router.include_router(...)` in `src/recruiter/main.py`, **never** `app.include_router(...)`. That is how every `/api` route gets the viewer read-only guard, and `tests/api/test_viewer_matrix.py` fails any route that lacks it.
- Frontend selects use the existing Radix `Select` from `@/components/ui/select` (the repo's convention; see `src/components/settings/llm-tab.tsx` and its test for how to drive one in jsdom). Checkboxes are native `<input type="checkbox">`, as elsewhere.
- Run the backend suite as `uv run pytest -q` **with an explicit `timeout: 400000` on the Bash call.** The harness backgrounds any call over 120 s and the suite takes about 3 minutes; without the timeout the run detaches and the agent stalls waiting for it.
- Record `uv run ruff check src/ tests/` at the start of Task 1. No task may raise that number, except that a new alembic migration file carries the generated header its siblings do.
- Every commit message ends with:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

---

## File Structure

**Created**
- `src/recruiter/models/interview_template.py` — the ORM table.
- `src/recruiter/schemas/interview_template.py` — request/response shapes and `TemplateSnapshot`.
- `src/recruiter/api/interview_templates.py` — CRUD router.
- `alembic/versions/20260923_000000_interview_templates.py` — one additive migration. (Filenames sort by date and the current head's file is `20260922_000000_drop_application_interview_kit.py`, so this one is dated after it.)
- `recruiter-frontend/src/hooks/use-interview-templates.ts` — list query and save mutation.
- `recruiter-frontend/src/components/interview/question-list-editor.tsx` — the row editor, extracted from the baseline sheet so both sheets share it.
- `recruiter-frontend/src/components/settings/interview-templates-tab.tsx` and `interview-template-sheet.tsx`.
- `recruiter-frontend/src/components/candidate/schedule-round-dialog.tsx` — the round-start picker.
- Tests beside each.

**Modified**
- `src/recruiter/models/__init__.py`, `models/job.py`, `models/interview_kit_row.py`
- `src/recruiter/pipeline/interview_kit.py` — the two assembly rules and `snapshot_of`.
- `src/recruiter/pipeline/kit_store.py` — template fields on `create_kit`, and helpers.
- `src/recruiter/api/interview.py` — generation reads the snapshot; kit read exposes `template_name`.
- `src/recruiter/api/applications.py` — resolve the round's template on scheduling and reopening.
- `src/recruiter/api/jobs.py`, `schemas/job.py`, `schemas/application.py`, `main.py`
- Frontend: `routes/settings.tsx`, `components/jobs/edit-interview-baseline-sheet.tsx`, `components/jobs/edit-job-details-sheet.tsx`, `components/candidate/action-bar.tsx`, `components/candidate/interview-kit-section.tsx`, `hooks/use-application-mutations.ts`, `hooks/use-interview-kit.ts`, `hooks/use-jobs.ts`, `lib/query-keys.ts`.

---

### Task 1: Tables, schemas and the migration

**Files:**
- Create: `src/recruiter/models/interview_template.py`
- Create: `src/recruiter/schemas/interview_template.py`
- Create: `alembic/versions/20260923_000000_interview_templates.py`
- Modify: `src/recruiter/models/__init__.py`, `src/recruiter/models/job.py`, `src/recruiter/models/interview_kit_row.py`
- Test: `tests/api/test_kit_migration.py` (extend)

**Interfaces:**
- Produces: `InterviewTemplate` (columns `id, name, description, questions, probe_mode, include_job_questions, is_active, created_at, updated_at`); `Job.default_interview_template_id: int | None`; `InterviewKitRow.template_id: int | None`, `template_name: str | None`, `template_snapshot: dict | None`; schemas `ProbeMode`, `TEMPLATE_QUESTION_ID_MAX`, `TemplateQuestion`, `InterviewTemplateCreate`, `InterviewTemplateUpdate`, `InterviewTemplateRead`, `TemplateSnapshot`; alembic revision `e6f2a9c4b1d3`.

- [ ] **Step 1: Record the ruff baseline**

Run: `uv run ruff check src/ tests/ 2>&1 | grep "^Found"` and note the number in your report.

- [ ] **Step 2: Write the schemas**

Create `src/recruiter/schemas/interview_template.py`:

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from recruiter.schemas.interview import BaselineQuestion

# "score_gaps": today's generator, driven by criteria and the score
# breakdown. "none": curated questions only, no LLM call. Phase 4 adds a
# profile-driven mode for RH-style templates.
ProbeMode = Literal["score_gaps", "none"]

# A template question is snapshotted into a kit as `t<template_id>-<id>`,
# and KitQuestion.id is capped at 64. Capping the template side here keeps
# every namespaced id inside that limit. Editor-minted UUIDs are 36.
TEMPLATE_QUESTION_ID_MAX = 48


class TemplateQuestion(BaselineQuestion):
    id: str = Field(min_length=1, max_length=TEMPLATE_QUESTION_ID_MAX)


class InterviewTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    questions: list[TemplateQuestion] = Field(default_factory=list)
    probe_mode: ProbeMode = "score_gaps"
    include_job_questions: bool = True


class InterviewTemplateUpdate(BaseModel):
    """Every field optional. Which ones the caller actually sent is read
    from `model_fields_set`, so `description: null` clears the description
    while an absent field leaves it alone."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    questions: list[TemplateQuestion] | None = None
    probe_mode: ProbeMode | None = None
    include_job_questions: bool | None = None
    is_active: bool | None = None


class InterviewTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    questions: list[TemplateQuestion]
    probe_mode: ProbeMode
    include_job_questions: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TemplateSnapshot(BaseModel):
    """What a kit was built from, frozen when the kit was created.

    Regeneration reads this, never the live template, so editing a
    template cannot rewrite a round already under way. `questions` are
    already namespaced (see `snapshot_of`).
    """

    questions: list[BaselineQuestion] = Field(default_factory=list)
    probe_mode: ProbeMode
    include_job_questions: bool
```

- [ ] **Step 3: Write the model**

Create `src/recruiter/models/interview_template.py`:

```python
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


class InterviewTemplate(Base):
    """An org-wide, reusable question set — "Technical", "RH screen".

    A round picks one when it starts; the kit snapshots it at creation
    (see interview_kits.template_snapshot), so editing a template never
    rewrites an existing kit. Archived rather than deleted, so kits and
    job defaults that point at it stay coherent.
    """

    __tablename__ = "interview_templates"
    __table_args__ = (
        # Unique among ACTIVE templates only, so an archived "RH screen"
        # does not block creating a new one with the same name.
        Index(
            "uq_interview_templates_active_name", "name",
            unique=True, postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String)
    questions: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    probe_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="score_gaps", server_default="score_gaps",
    )
    include_job_questions: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
```

In `src/recruiter/models/__init__.py` add, after the `interview_kit_row` import:

```python
from recruiter.models.interview_template import InterviewTemplate
```

and `"InterviewTemplate",` in `__all__` right after `"InterviewKitRow",`.

- [ ] **Step 4: Add the job default and the kit snapshot columns**

In `src/recruiter/models/job.py`, the import is currently `from sqlalchemy import Boolean, JSON, DateTime, Enum as SAEnum, String, func`; add `ForeignKey` and `Integer` to it, and this column after `interview_baseline`:

```python
    # The template preselected when a round starts. An archived template
    # is treated as no default. SET NULL keeps the job valid if a template
    # row is ever removed outright.
    default_interview_template_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("interview_templates.id", ondelete="SET NULL"),
    )
```

In `src/recruiter/models/interview_kit_row.py` (which already imports `ForeignKey`, `Integer`, `JSON` and `String`), add these three columns after `submitted_at`:

```python
    # Which template this kit was built from, if any. NULL for kits that
    # predate templates and for rounds started with "No template" — both
    # behave exactly as kits always have.
    template_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("interview_templates.id", ondelete="SET NULL"),
    )
    # A copy of the name at creation, so "Round 2 · RH screen" stays
    # readable after the template is renamed or archived.
    template_name: Mapped[str | None] = mapped_column(String(128))
    # TemplateSnapshot as a dict. Regeneration reads this, never the live
    # template.
    template_snapshot: Mapped[dict | None] = mapped_column(JSON)
```

- [ ] **Step 5: Write the migration**

Confirm the head first: `uv run alembic heads` — expected `d4b8c1f60a37 (head)`.

Create `alembic/versions/20260923_000000_interview_templates.py`:

```python
"""add interview templates, a job default, and kit template snapshots

Revision ID: e6f2a9c4b1d3
Revises: d4b8c1f60a37
Create Date: 2026-09-21 00:00:00.000000

Purely additive: every new column is nullable or defaulted, so there is
no backfill, existing kits keep behaving exactly as before (no template),
and the downgrade simply drops what this adds.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e6f2a9c4b1d3'
down_revision: Union[str, None] = 'd4b8c1f60a37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "interview_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("probe_mode", sa.String(length=16), nullable=False,
                  server_default="score_gaps"),
        sa.Column("include_job_questions", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "uq_interview_templates_active_name", "interview_templates", ["name"],
        unique=True, postgresql_where=sa.text("is_active"),
    )
    op.add_column("jobs", sa.Column(
        "default_interview_template_id", sa.Integer(),
        sa.ForeignKey("interview_templates.id", ondelete="SET NULL"), nullable=True,
    ))
    op.add_column("interview_kits", sa.Column(
        "template_id", sa.Integer(),
        sa.ForeignKey("interview_templates.id", ondelete="SET NULL"), nullable=True,
    ))
    op.add_column("interview_kits",
                  sa.Column("template_name", sa.String(length=128), nullable=True))
    op.add_column("interview_kits",
                  sa.Column("template_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("interview_kits", "template_snapshot")
    op.drop_column("interview_kits", "template_name")
    op.drop_column("interview_kits", "template_id")
    op.drop_column("jobs", "default_interview_template_id")
    op.drop_index("uq_interview_templates_active_name", table_name="interview_templates")
    op.drop_table("interview_templates")
```

- [ ] **Step 6: Write the failing migration test**

In `tests/api/test_kit_migration.py`, add `TEMPLATES = "e6f2a9c4b1d3"` beside the other revision constants, then append:

```python
def test_templates_migration_is_additive_and_reversible(postgres_container, monkeypatch) -> None:
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
            "INSERT INTO jobs (title, description, criteria, status, created_at, updated_at)"
            " VALUES ('J','d','[]','open',now(),now())"))
        conn.execute(sa.text(
            "INSERT INTO candidates (source_type, full_name, skills, experience, education,"
            " links, created_at, updated_at)"
            " VALUES ('paste','C','[]','[]','[]','[]',now(),now())"))
        conn.execute(sa.text(
            "INSERT INTO applications (job_id, candidate_id, stage, interview_round,"
            " created_at, updated_at)"
            " SELECT (SELECT id FROM jobs LIMIT 1), (SELECT id FROM candidates LIMIT 1),"
            " 'scheduled', 1, now(), now()"))
        conn.execute(sa.text(
            "INSERT INTO interview_kits (application_id, round, track, questions, status,"
            " created_at, updated_at)"
            " SELECT id, 1, 'default', '[{\"id\":\"b1\",\"text\":\"Why?\",\"source\":\"baseline\"}]',"
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
            "INSERT INTO interview_templates (name, questions) VALUES ('RH screen', '[]')"))
        conn.execute(sa.text(
            "UPDATE interview_templates SET is_active = false WHERE name = 'RH screen'"))
        conn.execute(sa.text(
            "INSERT INTO interview_templates (name, questions) VALUES ('RH screen', '[]')"))

    assert (kit["template_id"], kit["template_name"], kit["template_snapshot"]) == (None, None, None)
    assert kit["questions"][0]["id"] == "b1"
    assert job_default is None

    command.downgrade(cfg, LATEST)
    with engine.begin() as conn:
        tables = conn.execute(sa.text(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema='public'")).scalars().all()
        kit_count = conn.execute(sa.text("SELECT count(*) FROM interview_kits")).scalar_one()
    assert "interview_templates" not in tables
    assert kit_count == 1, "downgrading the templates migration lost a kit"

    # And back up again: the downgrade must leave nothing behind that
    # blocks re-applying the migration.
    command.upgrade(cfg, TEMPLATES)
    with engine.begin() as conn:
        assert conn.execute(sa.text(
            "SELECT count(*) FROM interview_templates")).scalar_one() == 0
```

- [ ] **Step 7: Run it**

Run: `uv run pytest tests/api/test_kit_migration.py -q`
Expected: PASS (the new test plus the existing ones). If the new test errors with `Can't locate revision 'e6f2a9c4b1d3'`, the migration file from Step 5 is missing or misnamed.

- [ ] **Step 8: Whole suite, heads, ruff**

Run: `uv run alembic heads` — expected exactly `e6f2a9c4b1d3 (head)`.
Run: `uv run pytest -q` (timeout 400000) — expected all pass. Nothing reads the new columns yet.
Run: `uv run ruff check src/ tests/` — not above the Step 1 number.

- [ ] **Step 9: Commit**

```bash
git add src/recruiter/models src/recruiter/schemas/interview_template.py alembic/versions tests/api/test_kit_migration.py
git commit -m "feat(interview-kit): add interview templates, a job default, and kit snapshots

Tables and schemas only; nothing reads them yet. A kit snapshots its
template at creation so editing a template can never rewrite a round
already under way, and a template name is unique only among active
templates so archiving frees it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The kit assembly rules

**Files:**
- Modify: `src/recruiter/pipeline/interview_kit.py`
- Test: `tests/unit/test_interview_kit_assembly.py` (extend)

**Interfaces:**
- Consumes: `InterviewTemplate`, `TemplateSnapshot` (Task 1).
- Produces:
  - `snapshot_of(template: InterviewTemplate) -> TemplateSnapshot`
  - `fixed_questions(snapshot: TemplateSnapshot | None, job_baseline: list[BaselineQuestion]) -> list[BaselineQuestion]`
  - `wants_probes(snapshot: TemplateSnapshot | None) -> bool`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_interview_kit_assembly.py`:

```python
from recruiter.models import InterviewTemplate
from recruiter.pipeline.interview_kit import fixed_questions, snapshot_of, wants_probes
from recruiter.schemas.interview_template import TemplateSnapshot


def _template(*, probe_mode: str, include: bool, qids=("b1",)) -> InterviewTemplate:
    tpl = InterviewTemplate(
        name="RH screen", probe_mode=probe_mode, include_job_questions=include,
        questions=[{"id": q, "text": f"Template {q}"} for q in qids],
    )
    tpl.id = 7
    return tpl


def _job_baseline():
    return [BaselineQuestion(id="b1", text="Job b1"), BaselineQuestion(id="b2", text="Job b2")]


def test_no_template_means_exactly_the_job_baseline_and_probes() -> None:
    """The guarantee that makes this phase safe to ship with zero templates."""
    assert [q.id for q in fixed_questions(None, _job_baseline())] == ["b1", "b2"]
    assert wants_probes(None) is True


def test_template_questions_are_namespaced_so_they_cannot_collide() -> None:
    """Sheets key answers by question id. A template question `b1` and the
    job's own `b1` must stay two questions, or their answers merge."""
    snap = snapshot_of(_template(probe_mode="score_gaps", include=True))
    ids = [q.id for q in fixed_questions(snap, _job_baseline())]

    assert ids == ["t7-b1", "b1", "b2"], "template first, then the job's own, all distinct"


def test_job_questions_left_out_when_the_template_says_so() -> None:
    snap = snapshot_of(_template(probe_mode="none", include=False))
    assert [q.text for q in fixed_questions(snap, _job_baseline())] == ["Template b1"]


def test_probe_mode_none_wants_no_probes() -> None:
    assert wants_probes(snapshot_of(_template(probe_mode="none", include=False))) is False
    assert wants_probes(snapshot_of(_template(probe_mode="score_gaps", include=True))) is True


def test_the_snapshot_survives_a_round_trip_through_the_database_shape() -> None:
    """The snapshot is stored as a dict on the kit row and read back later;
    the round trip must not lose the namespacing or the switches."""
    snap = snapshot_of(_template(probe_mode="none", include=False))
    again = TemplateSnapshot.model_validate(snap.model_dump())
    assert again == snap
```

(`BaselineQuestion` is already imported at the top of that file.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_interview_kit_assembly.py -q`
Expected: FAIL — `ImportError: cannot import name 'fixed_questions'`.

- [ ] **Step 3: Implement**

In `src/recruiter/pipeline/interview_kit.py`, add to the imports (the module path directly, not the `recruiter.models` package, to keep this module's imports as narrow as they are today):

```python
from recruiter.models.interview_template import InterviewTemplate
from recruiter.schemas.interview_template import TemplateSnapshot
```

and add these functions (keep them with the other kit-assembly helpers):

```python
def snapshot_of(template: InterviewTemplate) -> TemplateSnapshot:
    """Freeze a template into what a kit will be built from.

    Question ids are namespaced as `t<template_id>-<id>`. The editor mints
    UUIDs, but ids are client-supplied and not required to be — and a
    template question sharing an id with the job's own baseline would
    make sheets merge two questions' answers, since answers are keyed by
    question id. Job baseline ids are never rewritten: existing kits and
    sheets already reference them.
    """
    return TemplateSnapshot(
        questions=[
            BaselineQuestion.model_validate({**q, "id": f"t{template.id}-{q['id']}"})
            for q in (template.questions or [])
        ],
        probe_mode=template.probe_mode,
        include_job_questions=template.include_job_questions,
    )


def fixed_questions(
    snapshot: TemplateSnapshot | None, job_baseline: list[BaselineQuestion],
) -> list[BaselineQuestion]:
    """The questions a kit asks regardless of generation.

    No template → the job's baseline, exactly as kits have always been
    built. Otherwise the template's questions come first, so a shared
    standard opens the interview, followed by the job's own when the
    template includes them.
    """
    if snapshot is None:
        return list(job_baseline)
    return [
        *snapshot.questions,
        *(job_baseline if snapshot.include_job_questions else []),
    ]


def wants_probes(snapshot: TemplateSnapshot | None) -> bool:
    """Whether generation should call the LLM for probes. Probes come from
    the technical score breakdown, so an RH-style template switches them
    off rather than have technical questions appended to an HR round."""
    return snapshot is None or snapshot.probe_mode == "score_gaps"
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_interview_kit_assembly.py -q` — expected PASS.

- [ ] **Step 5: Whole suite and commit**

Run: `uv run pytest -q` (timeout 400000) — all pass.

```bash
git add src/recruiter/pipeline/interview_kit.py tests/unit/test_interview_kit_assembly.py
git commit -m "feat(interview-kit): the rules for building a kit from a template

Two pure functions decide a kit's fixed questions and whether it gets
generated probes, from a snapshot rather than the live template. With no
template they return exactly what kits have always been built from.
Template question ids are namespaced so they can never share an id with
the job's own questions, since sheets key answers by id.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Template CRUD and the job default

**Files:**
- Create: `src/recruiter/api/interview_templates.py`
- Modify: `src/recruiter/main.py`, `src/recruiter/schemas/job.py`, `src/recruiter/api/jobs.py`
- Test: `tests/api/test_interview_templates_api.py`

**Interfaces:**
- Consumes: Task 1's model and schemas.
- Produces: `GET /api/interview-templates?include_archived=false`, `POST /api/interview-templates` (201), `PATCH /api/interview-templates/{id}`; `JobRead.default_interview_template_id: int | None`; `JobUpdate.default_interview_template_id: int | None` (absent leaves it alone, `null` clears it).

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_interview_templates_api.py`:

```python
import pytest
from httpx import AsyncClient

from recruiter.auth.passwords import hash_password
from recruiter.models import Role, User

BASE = "/api/interview-templates"
Q = [{"id": "q1", "text": "Why this company?"}]


@pytest.mark.asyncio
async def test_create_then_list(api_client: AsyncClient) -> None:
    r = await api_client.post(BASE, json={
        "name": "RH screen", "questions": Q, "probe_mode": "none",
        "include_job_questions": False,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["probe_mode"], body["include_job_questions"], body["is_active"]) == (
        "none", False, True)

    listed = (await api_client.get(BASE)).json()
    assert [t["name"] for t in listed] == ["RH screen"]


@pytest.mark.asyncio
async def test_a_new_template_defaults_to_technical_behaviour(api_client: AsyncClient) -> None:
    body = (await api_client.post(BASE, json={"name": "Technical"})).json()
    assert (body["probe_mode"], body["include_job_questions"]) == ("score_gaps", True)


@pytest.mark.asyncio
async def test_duplicate_question_ids_are_refused(api_client: AsyncClient) -> None:
    r = await api_client.post(BASE, json={"name": "T", "questions": [
        {"id": "q1", "text": "a"}, {"id": "q1", "text": "b"}]})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_question_ids_longer_than_48_are_refused(api_client: AsyncClient) -> None:
    """A snapshotted id is t<template_id>-<id>, and kit ids are capped at 64."""
    r = await api_client.post(BASE, json={"name": "T", "questions": [
        {"id": "x" * 49, "text": "a"}]})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_names_are_unique_among_active_templates_only(api_client: AsyncClient) -> None:
    first = (await api_client.post(BASE, json={"name": "RH screen"})).json()
    clash = await api_client.post(BASE, json={"name": "RH screen"})
    assert clash.status_code == 409

    await api_client.patch(f"{BASE}/{first['id']}", json={"is_active": False})
    again = await api_client.post(BASE, json={"name": "RH screen"})
    assert again.status_code == 201, "archiving should free the name"


@pytest.mark.asyncio
async def test_archived_templates_are_hidden_unless_asked_for(api_client: AsyncClient) -> None:
    tpl = (await api_client.post(BASE, json={"name": "Old"})).json()
    await api_client.patch(f"{BASE}/{tpl['id']}", json={"is_active": False})

    assert (await api_client.get(BASE)).json() == []
    assert [t["name"] for t in (await api_client.get(f"{BASE}?include_archived=true")).json()] == ["Old"]


@pytest.mark.asyncio
async def test_patch_clears_description_but_refuses_nulling_a_required_field(
    api_client: AsyncClient,
) -> None:
    tpl = (await api_client.post(BASE, json={"name": "T", "description": "x"})).json()
    cleared = await api_client.patch(f"{BASE}/{tpl['id']}", json={"description": None})
    assert cleared.json()["description"] is None
    assert (await api_client.patch(f"{BASE}/{tpl['id']}", json={"name": None})).status_code == 422


@pytest.mark.asyncio
async def test_a_job_can_point_at_a_default_template(
    api_client: AsyncClient, create_scored_app,
) -> None:
    await create_scored_app()
    job = (await api_client.get("/api/jobs")).json()[0]
    tpl = (await api_client.post(BASE, json={"name": "Technical"})).json()

    set_ = await api_client.patch(f"/api/jobs/{job['id']}",
                                  json={"default_interview_template_id": tpl["id"]})
    assert set_.json()["default_interview_template_id"] == tpl["id"]

    # Absent leaves it alone; explicit null clears it.
    kept = await api_client.patch(f"/api/jobs/{job['id']}", json={"title": "Renamed"})
    assert kept.json()["default_interview_template_id"] == tpl["id"]
    cleared = await api_client.patch(f"/api/jobs/{job['id']}",
                                     json={"default_interview_template_id": None})
    assert cleared.json()["default_interview_template_id"] is None


@pytest.mark.asyncio
async def test_an_archived_template_cannot_become_a_job_default(
    api_client: AsyncClient, create_scored_app,
) -> None:
    await create_scored_app()
    job = (await api_client.get("/api/jobs")).json()[0]
    tpl = (await api_client.post(BASE, json={"name": "Old"})).json()
    await api_client.patch(f"{BASE}/{tpl['id']}", json={"is_active": False})

    r = await api_client.patch(f"/api/jobs/{job['id']}",
                               json={"default_interview_template_id": tpl["id"]})
    assert r.status_code == 422
```

Also add a viewer/recruiter check. It logs real users in, the same way `tests/api/test_interview_freeze_api.py` does, so it needs that file's helpers and its limiter reset:

(Add `from sqlalchemy.ext.asyncio import AsyncSession` to the imports at the top of the file, not here, or ruff's E402 fires.)

```python
PW = "pw-12345678"


@pytest.fixture(autouse=True)
def _reset_limiter():
    # Several logins per test; without a reset the shared 5/min login
    # budget trips across tests and files (see rate_limit.py).
    from recruiter.api.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


async def _add(session: AsyncSession, email: str, role: Role) -> User:
    user = User(email=email, role=role, is_active=True, password_hash=hash_password(PW))
    session.add(user)
    await session.commit()
    return user


async def _login(client: AsyncClient, email: str) -> None:
    await client.post("/api/auth/logout")
    r = await client.post("/api/auth/login/password", json={"email": email, "password": PW})
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_recruiters_manage_templates_and_viewers_cannot(
    api_client_unauth: AsyncClient, db_session_with_schema,
) -> None:
    await _add(db_session_with_schema, "rec@acme.com", Role.RECRUITER)
    await _add(db_session_with_schema, "view@acme.com", Role.VIEWER)

    await _login(api_client_unauth, "rec@acme.com")
    assert (await api_client_unauth.post(BASE, json={"name": "T"})).status_code == 201

    await _login(api_client_unauth, "view@acme.com")
    assert (await api_client_unauth.post(BASE, json={"name": "U"})).status_code == 403
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/api/test_interview_templates_api.py -q`
Expected: FAIL — 404s on `/api/interview-templates`.

- [ ] **Step 3: Write the router**

Create `src/recruiter/api/interview_templates.py`:

```python
"""Org-wide interview templates — "Technical", "RH screen".

Managed by admins and recruiters; viewers are refused by the /api router's
viewer read-only guard, which this router inherits by being registered on
`_api_router` in main.py. Templates are archived (`is_active=false`), never
deleted: kits hold their own snapshot, and archiving frees the name.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.deps import get_session, require_user
from recruiter.models import InterviewTemplate
from recruiter.schemas.interview_template import (
    InterviewTemplateCreate,
    InterviewTemplateRead,
    InterviewTemplateUpdate,
    TemplateQuestion,
)

router = APIRouter(
    prefix="/api/interview-templates", tags=["interview"], dependencies=[Depends(require_user)],
)

# Fields that may not be set to null through PATCH; only `description` can.
_REQUIRED = {"name", "questions", "probe_mode", "include_job_questions", "is_active"}


def _check_ids(questions: list[TemplateQuestion]) -> None:
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="duplicate question ids")


async def _commit_or_conflict(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="an active template already has that name",
        ) from exc


@router.get("", response_model=list[InterviewTemplateRead])
async def list_templates(
    include_archived: bool = False, session: AsyncSession = Depends(get_session),
) -> list[InterviewTemplate]:
    stmt = select(InterviewTemplate).order_by(InterviewTemplate.name)
    if not include_archived:
        stmt = stmt.where(InterviewTemplate.is_active.is_(True))
    return list((await session.execute(stmt)).scalars().all())


@router.post("", response_model=InterviewTemplateRead, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: InterviewTemplateCreate, session: AsyncSession = Depends(get_session),
) -> InterviewTemplate:
    _check_ids(payload.questions)
    tpl = InterviewTemplate(
        name=payload.name,
        description=payload.description,
        questions=[q.model_dump() for q in payload.questions],
        probe_mode=payload.probe_mode,
        include_job_questions=payload.include_job_questions,
    )
    session.add(tpl)
    await _commit_or_conflict(session)
    await session.refresh(tpl)
    return tpl


@router.patch("/{template_id}", response_model=InterviewTemplateRead)
async def update_template(
    template_id: int,
    payload: InterviewTemplateUpdate,
    session: AsyncSession = Depends(get_session),
) -> InterviewTemplate:
    tpl = await session.get(InterviewTemplate, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="template not found")
    for field in payload.model_fields_set:
        value = getattr(payload, field)
        if value is None and field in _REQUIRED:
            raise HTTPException(status_code=422, detail=f"{field} cannot be null")
        if field == "questions":
            _check_ids(value)
            value = [q.model_dump() for q in value]
        setattr(tpl, field, value)
    await _commit_or_conflict(session)
    await session.refresh(tpl)
    return tpl
```

In `src/recruiter/main.py`, import `interview_templates` alongside the other `recruiter.api` modules and register it **on `_api_router`**, next to `interview.router`:

```python
_api_router.include_router(interview_templates.router)
```

- [ ] **Step 4: Job default**

In `src/recruiter/schemas/job.py`, add to `JobUpdate`:

```python
    # Absent leaves it alone; explicit null clears it — distinguished by
    # model_fields_set in the handler, since both arrive as None.
    default_interview_template_id: int | None = None
```

and to `JobRead`, after `interview_baseline`:

```python
    default_interview_template_id: int | None = None
```

In `src/recruiter/api/jobs.py`, in `update_job` after the `enrichment_consent` block and before `await session.commit()`:

```python
    if "default_interview_template_id" in payload.model_fields_set:
        tid = payload.default_interview_template_id
        if tid is not None:
            tpl = await session.get(InterviewTemplate, tid)
            if tpl is None or not tpl.is_active:
                raise HTTPException(
                    status_code=422, detail="unknown or archived interview template",
                )
        job.default_interview_template_id = tid
```

add `InterviewTemplate` to the `recruiter.models` import, and in `_to_read` add
`default_interview_template_id=job.default_interview_template_id,` after `interview_baseline=`.

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/api/test_interview_templates_api.py tests/api/test_viewer_matrix.py -q`
Expected: PASS. If the viewer matrix fails naming `/api/interview-templates`, the router was registered on `app` instead of `_api_router`.

- [ ] **Step 6: Whole suite and commit**

Run: `uv run pytest -q` (timeout 400000); `uv run ruff check src/ tests/` not above baseline.

```bash
git add src/recruiter/api src/recruiter/main.py src/recruiter/schemas/job.py tests/api/test_interview_templates_api.py
git commit -m "feat(interview-kit): manage interview templates and set a job default

CRUD for org-wide templates, archived rather than deleted. The router
sits on _api_router so viewers are refused by the same guard as every
other /api route. A job gains an optional default template, which an
archived template cannot become.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Kits carry their template — scheduling, reopening, generation

**Files:**
- Modify: `src/recruiter/pipeline/kit_store.py`, `src/recruiter/api/interview.py`, `src/recruiter/api/applications.py`, `src/recruiter/schemas/application.py`
- Test: `tests/api/test_interview_template_rounds.py`

**Interfaces:**
- Consumes: `snapshot_of`, `fixed_questions`, `wants_probes` (Task 2); `InterviewTemplate`, `TemplateSnapshot` (Task 1).
- Produces:
  - `create_kit(..., template_id: int | None = None, template_name: str | None = None, template_snapshot: dict | None = None)`
  - `template_fields(template: InterviewTemplate | None) -> dict` — the three kit columns for a template, or three `None`s
  - `snapshot_from_row(row: InterviewKitRow | None) -> TemplateSnapshot | None`
  - `async job_default_template(session, app_row) -> InterviewTemplate | None` — the job's default if it exists and is active
  - `ApplicationUpdate.interview_template_id: int | None`
  - `InterviewKitRead.template_name: str | None`
  - `run_generate_kit(..., llm: LLMClient | None, ...)`: `None` is allowed, and is only valid when the kit's snapshot wants no probes

**A decision the spec leaves open, settled here:** re-entering `scheduled` in the **same** round (possible via reject → re-validate → re-invite) with an unfrozen kit restamps that kit's template from the choice made now, because the regeneration that follows rebuilds its questions. A frozen kit keeps its template; its questions cannot change, exactly as today's freeze already refuses regeneration.

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_interview_template_rounds.py`:

```python
"""Templates chosen at round start, snapshotted into the round's kit."""
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from recruiter.api.candidates import get_engine_dep, get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.models import Application, InterviewKitRow, InterviewTemplate, Job, Stage
from recruiter.schemas.interview import GeneratedQuestion, GeneratedQuestions

RH = [{"id": "m1", "text": "What draws you to us?"}]


def _llm() -> FakeLLMClient:
    return FakeLLMClient(structured_responses=[GeneratedQuestions(questions=[
        GeneratedQuestion(text="A generated probe.", criterion="x"),
    ])])


async def _db():
    return async_sessionmaker(app.dependency_overrides[get_engine_dep](), expire_on_commit=False)


async def _template(name: str, *, probe_mode: str, include: bool, questions=RH,
                    active: bool = True) -> int:
    async with (await _db())() as s:
        t = InterviewTemplate(name=name, questions=questions, probe_mode=probe_mode,
                              include_job_questions=include, is_active=active)
        s.add(t)
        await s.commit()
        return t.id


async def _invited(api_client: AsyncClient, create_scored_app, *, baseline=None) -> int:
    app_id = await create_scored_app()
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
    async with (await _db())() as s:
        await s.execute(update(Application).where(Application.id == app_id)
                        .values(stage=Stage.INVITED))
        if baseline is not None:
            job_id = (await s.get(Application, app_id)).job_id
            await s.execute(update(Job).where(Job.id == job_id)
                            .values(interview_baseline=baseline))
        await s.commit()
    return app_id


async def _kits(app_id: int) -> list[InterviewKitRow]:
    async with (await _db())() as s:
        return list((await s.execute(select(InterviewKitRow)
                     .where(InterviewKitRow.application_id == app_id)
                     .order_by(InterviewKitRow.round))).scalars().all())


async def _schedule(api_client, app_id, llm, **extra):
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        return await api_client.patch(f"/api/applications/{app_id}",
                                      json={"stage": "scheduled", **extra})
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_an_rh_template_builds_a_curated_kit_with_no_llm_call(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tid = await _template("RH screen", probe_mode="none", include=False)
    app_id = await _invited(api_client, create_scored_app,
                            baseline=[{"id": "b1", "text": "Job question"}])
    llm = _llm()

    r = await _schedule(api_client, app_id, llm, interview_template_id=tid)

    assert r.status_code == 200, r.text
    assert llm.calls == [], "probe_mode none must not call the model"
    body = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()
    assert body["template_name"] == "RH screen"
    assert body["kit"]["status"] == "ready"
    assert [q["id"] for q in body["kit"]["questions"]] == [f"t{tid}-m1"]


@pytest.mark.asyncio
async def test_a_technical_template_puts_its_questions_before_the_jobs_and_adds_probes(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tid = await _template("Technical", probe_mode="score_gaps", include=True)
    app_id = await _invited(api_client, create_scored_app,
                            baseline=[{"id": "b1", "text": "Job question"}])
    llm = _llm()

    await _schedule(api_client, app_id, llm, interview_template_id=tid)

    kit = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()["kit"]
    assert [q["text"] for q in kit["questions"]] == [
        "What draws you to us?", "Job question", "A generated probe."]
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_absent_uses_the_job_default_and_null_uses_none(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tid = await _template("RH screen", probe_mode="none", include=False)
    first = await _invited(api_client, create_scored_app)
    job_id = (await api_client.get(f"/api/applications/{first}")).json()["job_id"]
    await api_client.patch(f"/api/jobs/{job_id}", json={"default_interview_template_id": tid})

    await _schedule(api_client, first, _llm())
    assert (await _kits(first))[0].template_id == tid

    second = await _invited(api_client, create_scored_app)
    await _schedule(api_client, second, _llm(), interview_template_id=None)
    assert (await _kits(second))[0].template_id is None


@pytest.mark.asyncio
async def test_an_archived_template_is_refused(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tid = await _template("Old", probe_mode="none", include=False, active=False)
    app_id = await _invited(api_client, create_scored_app)
    r = await _schedule(api_client, app_id, _llm(), interview_template_id=tid)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_a_template_with_any_other_stage_is_refused(
    api_client: AsyncClient, create_scored_app,
) -> None:
    app_id = await create_scored_app()
    r = await api_client.patch(f"/api/applications/{app_id}",
                               json={"stage": "validated", "interview_template_id": None})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_editing_a_template_does_not_change_a_kit_built_from_it(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tid = await _template("RH screen", probe_mode="none", include=False)
    app_id = await _invited(api_client, create_scored_app)
    await _schedule(api_client, app_id, _llm(), interview_template_id=tid)

    await api_client.patch(f"/api/interview-templates/{tid}",
                           json={"name": "Renamed", "questions": [{"id": "z9", "text": "New"}]})
    # Regenerate: must rebuild from the snapshot, not the edited template.
    app.dependency_overrides[get_llm] = _llm
    try:
        r = await api_client.post(f"/api/applications/{app_id}/interview-kit/generate")
        assert r.status_code == 202, r.text
    finally:
        app.dependency_overrides.pop(get_llm, None)

    body = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()
    assert [q["id"] for q in body["kit"]["questions"]] == [f"t{tid}-m1"]
    assert body["template_name"] == "RH screen", "regeneration wiped the template name"


async def _interview_and_close(api_client: AsyncClient, app_id: int) -> None:
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "interviewed"})


@pytest.mark.asyncio
async def test_reopening_with_the_same_template_copies_the_kit_forward(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tid = await _template("RH screen", probe_mode="none", include=False)
    app_id = await _invited(api_client, create_scored_app)
    await _schedule(api_client, app_id, _llm(), interview_template_id=tid)
    await _interview_and_close(api_client, app_id)

    await _schedule(api_client, app_id, _llm(), interview_template_id=tid)

    r1, r2 = await _kits(app_id)
    assert r2.template_id == tid and r2.template_snapshot == r1.template_snapshot
    assert [q["id"] for q in r2.questions] == [q["id"] for q in r1.questions]


@pytest.mark.asyncio
async def test_reopening_with_a_different_template_seeds_fresh(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tech = await _template("Technical", probe_mode="none", include=False,
                           questions=[{"id": "k8s", "text": "Clusters?"}])
    rh = await _template("RH screen", probe_mode="none", include=False)
    app_id = await _invited(api_client, create_scored_app)
    await _schedule(api_client, app_id, _llm(), interview_template_id=tech)
    await _interview_and_close(api_client, app_id)

    await _schedule(api_client, app_id, _llm(), interview_template_id=rh)

    r1, r2 = await _kits(app_id)
    assert r2.template_id == rh
    assert [q["id"] for q in r2.questions] == [f"t{rh}-m1"], (
        "the RH round inherited the technical round's questions")


@pytest.mark.asyncio
async def test_with_no_templates_scheduling_is_unchanged(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """The guarantee that makes this phase safe to ship."""
    app_id = await _invited(api_client, create_scored_app,
                            baseline=[{"id": "b1", "text": "Job question"}])
    llm = _llm()

    await _schedule(api_client, app_id, llm)

    body = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()
    assert body["template_name"] is None
    assert [q["id"] for q in body["kit"]["questions"]][0] == "b1"
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_a_template_without_probes_needs_no_llm_provider(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """With no provider configured, scheduling fails a kit with "No LLM
    provider configured". A template that generates nothing must not be
    failed for want of a model it never calls. No get_llm override here:
    the fresh test database has no settings row, so get_llm_or_none
    resolves to None exactly as it does in an unconfigured install."""
    tid = await _template("RH screen", probe_mode="none", include=False)
    app_id = await _invited(api_client, create_scored_app)

    r = await api_client.patch(f"/api/applications/{app_id}",
                               json={"stage": "scheduled", "interview_template_id": tid})

    assert r.status_code == 200, r.text
    kit = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()["kit"]
    assert kit["status"] == "ready", kit.get("error")
    assert [q["id"] for q in kit["questions"]] == [f"t{tid}-m1"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/api/test_interview_template_rounds.py -q`
Expected: FAIL — `interview_template_id` is ignored or rejected, and `template_name` is missing from the kit read.

- [ ] **Step 3: Store helpers**

In `src/recruiter/pipeline/kit_store.py`:

1. Add three keyword arguments to `create_kit` after `error`, and pass them to the row:

```python
    template_id: int | None = None,
    template_name: str | None = None,
    template_snapshot: dict | None = None,
```

```python
    row = InterviewKitRow(
        application_id=app_row.id, round=round, track=track,
        questions=questions or [], status=status, error=error,
        template_id=template_id, template_name=template_name,
        template_snapshot=template_snapshot,
    )
```

2. Add these functions (imports: `InterviewTemplate`, `Job` from `recruiter.models`; `snapshot_of` from `recruiter.pipeline.interview_kit`; `TemplateSnapshot` from `recruiter.schemas.interview_template`):

```python
def template_fields(template: InterviewTemplate | None) -> dict:
    """The three kit columns for a template — spread into create_kit, or
    set on an existing row. None yields three Nones: no template."""
    if template is None:
        return {"template_id": None, "template_name": None, "template_snapshot": None}
    return {
        "template_id": template.id,
        "template_name": template.name,
        "template_snapshot": snapshot_of(template).model_dump(),
    }


def snapshot_from_row(row: InterviewKitRow | None) -> TemplateSnapshot | None:
    if row is None or row.template_snapshot is None:
        return None
    return TemplateSnapshot.model_validate(row.template_snapshot)


async def job_default_template(
    session: AsyncSession, app_row: Application,
) -> InterviewTemplate | None:
    """The job's default template, if it has one and it is still active.
    An archived default is treated as no default."""
    job = await session.get(Job, app_row.job_id)
    if job is None or job.default_interview_template_id is None:
        return None
    template = await session.get(InterviewTemplate, job.default_interview_template_id)
    return template if template is not None and template.is_active else None
```

- [ ] **Step 4: Generation reads the snapshot; the kit read exposes the name**

In `src/recruiter/api/interview.py`:

Add `template_name: str | None = None` to `InterviewKitRead`.

In `_read`, pass `template_name=row.template_name if row else None` to `InterviewKitRead`.

In `run_generate_kit`, right after `dispatch_round = app_row.interview_round`, add:

```python
        # Built from what the kit was created with, never the live template:
        # editing a template must not rewrite a round already under way.
        snapshot = snapshot_from_row(kit_row)
```

and replace the start of the `try` body — the `baseline = [...]` assignment and the `generate_probes` call — with:

```python
            job_baseline = [BaselineQuestion.model_validate(b)
                            for b in (job.interview_baseline or [])]
            baseline = fixed_questions(snapshot, job_baseline)
            if wants_probes(snapshot):
                if llm is None:
                    # patch_application only dispatches without a model
                    # when the snapshot wants no probes; recorded as an
                    # error kit by the except below if that ever changes.
                    raise RuntimeError("No LLM provider configured. Set one up in Settings.")
                generated = await generate_probes(
                    profile=profile_text(candidate, enrichment=app_row.enrichment),
                    criteria=[CriteriaItem.model_validate(c) for c in (job.criteria or [])],
                    score_breakdown=app_row.score_breakdown,
                    baseline=baseline,
                    llm=llm,
                )
                texts = [q.text for q in generated.questions]
                criteria_by_probe = [q.criterion for q in generated.questions]
```

(`texts` and `criteria_by_probe` already default to `[]` above the `try`, so a `none` template leaves them empty and the kit is built from its fixed questions alone.)

Change `run_generate_kit`'s signature to accept `llm: LLMClient | None`.

Leave the `if kit_row is None: kit_row = await create_kit(...)` fallback near the end of `run_generate_kit` as it is, with no template. It only fires when no row existed at dispatch, in which case `snapshot` was `None` and the kit was built without a template, so stamping one there would misdescribe it.

In `generate_kit`, where a kit is created for an application that has none, stamp the job default so a from-scratch Generate behaves like an absent choice at scheduling:

```python
        kit_row = await create_kit(
            session, app_row, round=app_row.interview_round,
            **template_fields(await job_default_template(session, app_row)),
        )
```

Import `fixed_questions`, `wants_probes` from `recruiter.pipeline.interview_kit` and `job_default_template`, `snapshot_from_row`, `template_fields` from `recruiter.pipeline.kit_store`.

- [ ] **Step 5: Resolve the round's template on scheduling and reopening**

In `src/recruiter/schemas/application.py`, add to `ApplicationUpdate`:

```python
    # Which template the round being started uses. Only meaningful with
    # stage "scheduled". Absent → the job's default; explicit null → no
    # template; an id → that template. Absent and null both arrive as None,
    # so the handler reads model_fields_set to tell them apart.
    interview_template_id: int | None = None
```

In `src/recruiter/api/applications.py`, add this helper near `_open_next_round`:

```python
async def _resolve_round_template(
    session: AsyncSession, app_row: Application, payload: ApplicationUpdate,
) -> InterviewTemplate | None:
    if "interview_template_id" not in payload.model_fields_set:
        return await job_default_template(session, app_row)
    if payload.interview_template_id is None:
        return None
    template = await session.get(InterviewTemplate, payload.interview_template_id)
    if template is None or not template.is_active:
        raise HTTPException(status_code=422, detail="unknown or archived interview template")
    return template
```

In `patch_application`, before `schedule_kit_generation = False`, refuse a template without scheduling:

```python
    if "interview_template_id" in payload.model_fields_set and payload.stage != "scheduled":
        raise HTTPException(
            status_code=422,
            detail="interview_template_id is only meaningful when scheduling a round",
        )
```

Inside `if payload.stage is not None:`, right after `_validate_transition(...)`, resolve once:

```python
        round_template = (
            await _resolve_round_template(session, app_row, payload)
            if new_stage == Stage.SCHEDULED else None
        )
```

Change the reopen branch to pass the template and schedule generation when a fresh kit is seeded:

```python
        elif new_stage == Stage.SCHEDULED and previous_stage == Stage.INTERVIEWED:
            app_row.scheduled_at = now
            if await _open_next_round(session, app_row, round_template, now):
                schedule_kit_generation = True
```

In the first-scheduling branch's `else:` (the not-frozen path), replace the `if kit_row is None: kit_row = await create_kit(...)` lines with:

```python
                if kit_row is None:
                    kit_row = await create_kit(
                        session, app_row, round=app_row.interview_round,
                        **template_fields(round_template),
                    )
                else:
                    # Same round re-entered with an unfrozen kit: the
                    # regeneration below rebuilds its questions, so build
                    # them from the template chosen now.
                    for column, value in template_fields(round_template).items():
                        setattr(kit_row, column, value)
```

(The frozen branch is left as it is: a frozen kit keeps its template, because its questions cannot change.)

Replace `_open_next_round` so it takes the chosen template and reports whether a fresh kit needs generating:

```python
async def _open_next_round(
    session: AsyncSession, app_row: Application,
    template: InterviewTemplate | None, now: datetime,
) -> bool:
    """Reopen an interviewed application for another round.

    The closed round's sheets stay as they are and the panel is copied
    forward with empty sheets. The new round's kit follows the template
    chosen for it:

    - the same template as the closed round (including none → none):
      copy the questions forward together with the snapshot, so a
      follow-up round regenerates from what the first was built on even
      if the template has since been edited;
    - a different template: seed fresh from it. Copying a technical
      round's questions into an RH round is what templates exist to stop.

    Returns True when the new kit must be generated.
    """
    previous_round = app_row.interview_round
    panel = rows_in_round(await load_assignments(session, app_row.id), previous_round)
    previous_kit = await kit_for(session, app_row)  # still the old round here

    app_row.interview_round = previous_round + 1
    app_row.interviewed_at = None
    for row in panel:
        session.add(InterviewAssignment(
            application_id=app_row.id, user_id=row.user_id,
            round=app_row.interview_round, sheet=empty_sheet(),
        ))

    chosen_id = template.id if template is not None else None
    if previous_kit is not None and previous_kit.template_id == chosen_id:
        await create_kit(
            session, app_row, round=app_row.interview_round,
            questions=list(previous_kit.questions or []),
            status=previous_kit.status, error=previous_kit.error,
            template_id=previous_kit.template_id,
            template_name=previous_kit.template_name,
            template_snapshot=previous_kit.template_snapshot,
        )
        return False
    if previous_kit is None and template is None:
        return False  # nothing to copy and nothing chosen: as today

    kit = await create_kit(
        session, app_row, round=app_row.interview_round, status="generating",
        **template_fields(template),
    )
    kit.generating_since = now.isoformat()
    return True
```

At the end of `patch_application`, the dispatch currently reads `if schedule_kit_generation:` → `if llm is not None:` enqueue, `else:` mark the kit "No LLM provider configured". A template with `probe_mode: "none"` needs no model, so it must still be enqueued without one. Replace the inner `if llm is not None:` line with:

```python
        # A template without probes builds its kit with no model call, so a
        # missing provider must not fail it.
        needs_llm = wants_probes(snapshot_from_row(await kit_for(session, app_row)))
        if llm is not None or not needs_llm:
```

leaving the `background_tasks.add_task(run_generate_kit, ...)` body and the whole `else:` branch unchanged.

Import `InterviewTemplate` from `recruiter.models`; `job_default_template`, `snapshot_from_row`, `template_fields` from `recruiter.pipeline.kit_store`; and `wants_probes` from `recruiter.pipeline.interview_kit`.

- [ ] **Step 6: Run to verify they pass**

Run: `uv run pytest tests/api/test_interview_template_rounds.py tests/api/test_interview_rounds.py tests/api/test_interview_stage_wiring.py -q`
Expected: PASS — the new tests, and the existing rounds and generation tests unchanged.

- [ ] **Step 7: Whole suite and commit**

Run: `uv run pytest -q` (timeout 400000); `uv run ruff check src/ tests/` not above baseline.

```bash
git add src/recruiter tests/api/test_interview_template_rounds.py
git commit -m "feat(interview-kit): a round's kit is built from the template chosen for it

Scheduling and reopening take an optional interview_template_id: absent
uses the job's default, null uses none. The kit snapshots the template,
and generation reads the snapshot, so an RH template yields curated
questions with no model call while editing a template never rewrites a
round under way. Reopening with the same template copies forward as
before; a different one seeds fresh.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Frontend — shared question editor, Settings tab, job default

**Files:**
- Create: `recruiter-frontend/src/components/interview/question-list-editor.tsx`
- Create: `recruiter-frontend/src/hooks/use-interview-templates.ts`
- Create: `recruiter-frontend/src/components/settings/interview-templates-tab.tsx`, `interview-template-sheet.tsx`, and `interview-templates-tab.test.tsx`
- Create: `recruiter-frontend/src/components/jobs/edit-job-details-sheet.test.tsx`
- Modify: `recruiter-frontend/src/components/jobs/edit-interview-baseline-sheet.tsx`, `recruiter-frontend/src/routes/settings.tsx`, `recruiter-frontend/src/components/jobs/edit-job-details-sheet.tsx`, `recruiter-frontend/src/hooks/use-jobs.ts`, `recruiter-frontend/src/lib/query-keys.ts`

**Interfaces:**
- Consumes: the Task 3 endpoints.
- Produces: `useInterviewTemplates(includeArchived?: boolean)`, `useSaveInterviewTemplate()`, type `InterviewTemplate`; `queryKeys.interviewTemplates(includeArchived: boolean)`; `QuestionListEditor`; `JobRead.default_interview_template_id?: number | null`.

- [ ] **Step 1: Extract the question editor, behaviour-preserving**

Create `src/components/interview/question-list-editor.tsx` holding the row editor currently inline in `edit-interview-baseline-sheet.tsx` — the "Add question" button, the empty message, and the `Label` + `Input` + remove-button rows — plus `newQuestionId()` (the moved `newBaselineId`, same body):

```tsx
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export interface EditableQuestion {
  id: string;
  text: string;
  criterion?: string | null;
}

// A bare `Date.now()` collides when two rows are added within the same
// millisecond, and the rows then track each other's edits (they share an
// id). Prefer the collision-proof `crypto.randomUUID()`; fall back to a
// monotonic counter appended to the timestamp where it isn't available.
let questionIdCounter = 0;

export function newQuestionId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  questionIdCounter += 1;
  return `b-${Date.now()}-${questionIdCounter}`;
}

interface Props {
  rows: EditableQuestion[];
  onChange: (rows: EditableQuestion[]) => void;
  canWrite: boolean;
  /** Label for each row, e.g. "Baseline question" → "Baseline question 1". */
  labelPrefix: string;
  /** Prefix of each input's DOM id, e.g. "baseline" → `baseline-<row id>`. */
  idPrefix: string;
  emptyMessage: React.ReactNode;
}

export function QuestionListEditor({
  rows, onChange, canWrite, labelPrefix, idPrefix, emptyMessage,
}: Props) {
  const update = (i: number, text: string) =>
    onChange(rows.map((r, idx) => (idx === i ? { ...r, text } : r)));
  const remove = (i: number) => onChange(rows.filter((_, idx) => idx !== i));
  const add = () => onChange([...rows, { id: newQuestionId(), text: "" }]);

  return (
    <>
      {canWrite && (
        <div className="flex items-center gap-2 py-3 border-b">
          <Button type="button" variant="outline" size="sm" onClick={add}>
            <Plus className="h-4 w-4 mr-1" />
            Add question
          </Button>
        </div>
      )}
      <div className="flex-1 overflow-y-auto space-y-4 py-4">
        {rows.length === 0 && (
          <p className="text-sm text-muted-foreground italic">{emptyMessage}</p>
        )}
        {rows.map((row, i) => (
          <div key={row.id} className="flex gap-2 items-end">
            <div className="flex-1 space-y-1">
              <Label htmlFor={`${idPrefix}-${row.id}`}>{labelPrefix} {i + 1}</Label>
              <Input
                id={`${idPrefix}-${row.id}`}
                value={row.text}
                onChange={(e) => update(i, e.target.value)}
                readOnly={!canWrite}
              />
            </div>
            {canWrite && (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                // Deliberately doesn't repeat the row label: any lookup
                // matching on it would otherwise resolve both the input and
                // this button and pick whichever sorts last.
                aria-label={`Remove question ${i + 1}`}
                onClick={() => remove(i)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
```

In `edit-interview-baseline-sheet.tsx`, delete the inline editor (the `{canWrite && (<div …>Add question…</div>)}` block and the scrolling `<div className="flex-1 overflow-y-auto …">` after it), `newBaselineId` with its counter, the `update`/`remove`/`add` functions, and the now-unused `Plus`, `Trash2`, `Input` and `Label` imports, and render in their place:

```tsx
        <QuestionListEditor
          rows={rows}
          onChange={setRows}
          canWrite={canWrite}
          labelPrefix="Baseline question"
          idPrefix="baseline"
          emptyMessage={canWrite
            ? <>No baseline questions yet. Use <em>Add question</em> to start.</>
            : "No baseline questions set for this job yet."}
        />
```

Keep `export interface BaselineQuestion` in that file (other modules import it).

Run: `cd recruiter-frontend && npx vitest --run src/components/jobs/edit-interview-baseline-sheet.test.tsx`
Expected: PASS, **with no change to that test file**. This step is a pure extraction; if a baseline test fails, the markup moved — fix the component, not the test.

- [ ] **Step 2: Query key, hook, and the job type**

In `src/lib/query-keys.ts` add:

```ts
  interviewTemplates: (includeArchived: boolean) =>
    ["interview-templates", includeArchived] as const,
```

In `src/hooks/use-jobs.ts`, add to `JobRead`: `default_interview_template_id?: number | null;`

Create `src/hooks/use-interview-templates.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import type { EditableQuestion } from "@/components/interview/question-list-editor";

export type ProbeMode = "score_gaps" | "none";

export interface InterviewTemplate {
  id: number;
  name: string;
  description: string | null;
  questions: EditableQuestion[];
  probe_mode: ProbeMode;
  include_job_questions: boolean;
  is_active: boolean;
}

export type InterviewTemplateInput = Omit<InterviewTemplate, "id" | "is_active">;

export function useInterviewTemplates(includeArchived = false) {
  return useQuery({
    queryKey: queryKeys.interviewTemplates(includeArchived),
    queryFn: () =>
      api<InterviewTemplate[]>(`/api/interview-templates?include_archived=${includeArchived}`),
  });
}

/** Create when `id` is undefined, otherwise PATCH. Archiving is a PATCH of
 *  `{ is_active: false }`. Invalidates both archived and active lists. */
export function useSaveInterviewTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id?: number; body: Partial<InterviewTemplate> }) =>
      id === undefined
        ? api<InterviewTemplate>("/api/interview-templates", { method: "POST", json: body })
        : api<InterviewTemplate>(`/api/interview-templates/${id}`, { method: "PATCH", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["interview-templates"] }),
  });
}
```

- [ ] **Step 3: Write the failing Settings tab test**

Create `src/components/settings/interview-templates-tab.test.tsx`. Use msw like `src/components/settings/llm-tab.test.tsx` (copy its `setupServer` / `QueryClientProvider` wrapper pattern and how it drives a Radix `Select`):

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { InterviewTemplatesTab } from "./interview-templates-tab";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const RH = { id: 3, name: "RH screen", description: null, questions: [],
             probe_mode: "none", include_job_questions: false, is_active: true };

function mount(templates: unknown[], capture: { body?: any; path?: string } = {}) {
  server.use(
    http.get("http://localhost:8000/api/interview-templates", () => HttpResponse.json(templates)),
    http.post("http://localhost:8000/api/interview-templates", async ({ request }) => {
      capture.body = await request.json();
      return HttpResponse.json({ ...RH, id: 9, ...capture.body }, { status: 201 });
    }),
    http.patch("http://localhost:8000/api/interview-templates/:id", async ({ request, params }) => {
      capture.body = await request.json();
      capture.path = String(params.id);
      return HttpResponse.json({ ...RH, ...capture.body });
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><InterviewTemplatesTab /></QueryClientProvider>);
}

describe("InterviewTemplatesTab", () => {
  it("lists templates with what each one does", async () => {
    mount([RH]);
    await waitFor(() => expect(screen.getByText("RH screen")).toBeInTheDocument());
    expect(screen.getByText(/no generated probes/i)).toBeInTheDocument();
  });

  it("creates a template", async () => {
    const capture: { body?: any } = {};
    mount([], capture);
    await userEvent.click(await screen.findByRole("button", { name: /new template/i }));
    await userEvent.type(screen.getByLabelText(/^name$/i), "Technical");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(capture.body?.name).toBe("Technical"));
    expect(capture.body.probe_mode).toBe("score_gaps");
    expect(capture.body.include_job_questions).toBe(true);
  });

  it("edits a template", async () => {
    const capture: { body?: any; path?: string } = {};
    mount([RH], capture);
    await userEvent.click(await screen.findByRole("button", { name: /edit rh screen/i }));
    const name = screen.getByLabelText(/^name$/i);
    await userEvent.clear(name);
    await userEvent.type(name, "RH interview");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(capture.body?.name).toBe("RH interview"));
    expect(capture.path).toBe("3");
  });

  it("archives a template", async () => {
    const capture: { body?: any; path?: string } = {};
    mount([RH], capture);
    await userEvent.click(await screen.findByRole("button", { name: /archive rh screen/i }));
    await waitFor(() => expect(capture.body).toEqual({ is_active: false }));
    expect(capture.path).toBe("3");
  });
});
```

Run: `npx vitest --run src/components/settings/interview-templates-tab.test.tsx`
Expected: FAIL — the module does not exist.

- [ ] **Step 4: Build the tab and the sheet**

Create `src/components/settings/interview-template-sheet.tsx`: a `Sheet` (same shell as `edit-interview-baseline-sheet.tsx`) holding —
- `Label` "Name" + `Input` (`id="template-name"`),
- `Label` "Description" + `Textarea`,
- `Label` "Generated probes" + Radix `Select` with items `score_gaps` → "From score gaps (technical)" and `none` → "None — curated questions only",
- a native checkbox labelled "Include the job's own questions",
- `QuestionListEditor` with `labelPrefix="Template question"` and `idPrefix="template-question"`, always `canWrite` (only admins and recruiters reach this tab),
- Cancel and Save. Save calls `useSaveInterviewTemplate().mutate({ id: template?.id, body })` where `body` is `{ name, description: description || null, probe_mode, include_job_questions, questions: rows.filter(r => r.text.trim()) }`, then closes the sheet; on error, `toast.error(err instanceof ApiError ? err.detail : "Couldn't save template")`. A new template starts with `probe_mode: "score_gaps"` and the checkbox ticked, matching the backend defaults.

Create `src/components/settings/interview-templates-tab.tsx`:
- a "New template" button that opens the sheet with no template;
- a "Show archived" native checkbox switching `useInterviewTemplates(showArchived)`;
- one row per template: its name; a caption built from `probe_mode === "none" ? "No generated probes" : "Probes from score gaps"` and `include_job_questions ? " · includes the job's own questions" : ""`; an "Edit" button with `aria-label={`Edit ${t.name}`}` opening the sheet with that template; an "Archive" / "Unarchive" button with `aria-label={`${t.is_active ? "Archive" : "Unarchive"} ${t.name}`}` that PATCHes `{ is_active: !t.is_active }`;
- an empty state: "No templates yet. Without one, every round is built from the job's own questions, as before."

Export `InterviewTemplatesTab`.

In `src/routes/settings.tsx`, after `const isAdmin = ...`, add
`const canManageTemplates = me.data?.role === "admin" || me.data?.role === "recruiter";`, a trigger `{canManageTemplates && <TabsTrigger value="templates">Interview templates</TabsTrigger>}` after the Enrichment trigger, and the matching `TabsContent value="templates"` rendering `<InterviewTemplatesTab />` with `className="pt-6"`.

- [ ] **Step 5: Job default select**

First write the failing test. There is no test file for this sheet yet; create `src/components/jobs/edit-job-details-sheet.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import type { JobRead } from "@/hooks/use-jobs";
import { EditJobDetailsSheet } from "./edit-job-details-sheet";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const JOB: JobRead = {
  id: 6, title: "Backend", description: "JD", criteria: [], status: "open",
  default_interview_template_id: null,
  created_at: "2026-09-21T00:00:00Z", updated_at: "2026-09-21T00:00:00Z",
};
const RH = { id: 3, name: "RH screen", description: null, questions: [],
             probe_mode: "none", include_job_questions: false, is_active: true };

function mount(job: JobRead, capture: { body?: any }) {
  server.use(
    http.get("http://localhost:8000/api/interview-templates", () => HttpResponse.json([RH])),
    http.patch("http://localhost:8000/api/jobs/6", async ({ request }) => {
      capture.body = await request.json();
      return HttpResponse.json({ ...job, ...capture.body });
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <EditJobDetailsSheet job={job} open onOpenChange={() => {}} canWrite />
    </QueryClientProvider>,
  );
}

describe("EditJobDetailsSheet — default interview template", () => {
  it("saves the chosen default", async () => {
    const capture: { body?: any } = {};
    mount(JOB, capture);

    await userEvent.click(
      await screen.findByRole("combobox", { name: /default interview template/i }));
    await userEvent.click(await screen.findByRole("option", { name: /rh screen/i }));
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(capture.body?.default_interview_template_id).toBe(3));
  });

  it("does not resend an untouched default, so an archived one cannot block a title save", async () => {
    // Job 6's default (template 99) has since been archived: it is not in
    // the active list. Re-sending it would make the server refuse the save.
    const capture: { body?: any } = {};
    mount({ ...JOB, default_interview_template_id: 99 }, capture);

    const title = await screen.findByLabelText(/^title$/i);
    await userEvent.clear(title);
    await userEvent.type(title, "Platform");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(capture.body?.title).toBe("Platform"));
    expect(capture.body).not.toHaveProperty("default_interview_template_id");
  });
});
```

Run: `npx vitest --run src/components/jobs/edit-job-details-sheet.test.tsx`. Expected: FAIL, because there is no such combobox yet.

Then in `src/components/jobs/edit-job-details-sheet.tsx`:
- read `const templates = useInterviewTemplates(false).data ?? [];`
- add `const [defaultTemplate, setDefaultTemplate] = useState<number | null>(job.default_interview_template_id ?? null);` and reset it inside the existing `useEffect`'s `if (open)` block, adding `job.default_interview_template_id` to that effect's dependency list;
- below the description field, render a `Label` "Default interview template" and a Radix `Select`:

```tsx
          <div className="space-y-1">
            <Label htmlFor="job-default-template">Default interview template</Label>
            <Select
              // An archived or unknown default is not in the active list and
              // is treated as none, as the server does at round start.
              value={templates.some((t) => t.id === defaultTemplate) ? String(defaultTemplate) : "none"}
              onValueChange={(v) => setDefaultTemplate(v === "none" ? null : Number(v))}
              disabled={!canWrite}
            >
              <SelectTrigger id="job-default-template" aria-label="Default interview template">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">None — the job's own questions</SelectItem>
                {templates.map((t) => (
                  <SelectItem key={t.id} value={String(t.id)}>{t.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
```

- compute `const defaultDirty = defaultTemplate !== (job.default_interview_template_id ?? null);`, add it to `canSave`'s dirty check, and send the field **only when it changed**:

```ts
        json: {
          title,
          description,
          ...(defaultDirty ? { default_interview_template_id: defaultTemplate } : {}),
        },
```

Re-run the test above. Expected: PASS.

- [ ] **Step 6: Verify and commit**

Run: `npx vitest --run` — all pass; `npm run lint` — clean; `npm run build` — succeeds.

```bash
git add recruiter-frontend/src
git commit -m "feat(interview-kit): manage templates in Settings and pick a job default

The baseline sheet's question editor is extracted so templates reuse it,
with the baseline tests unchanged as the proof the extraction moved
nothing. Admins and recruiters get an Interview templates tab; a job can
choose which template a round starts from by default.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Frontend — the round picker and the kit header

**Files:**
- Create: `recruiter-frontend/src/components/candidate/schedule-round-dialog.tsx` and its test
- Modify: `recruiter-frontend/src/components/candidate/action-bar.tsx`, `action-bar.test.tsx` (mock and PATCH lookup only, plus one new test), `recruiter-frontend/src/routes/application-detail.test.tsx` (one msw handler), `recruiter-frontend/src/hooks/use-application-mutations.ts`, `recruiter-frontend/src/hooks/use-interview-kit.ts`, `recruiter-frontend/src/components/candidate/interview-kit-section.tsx`

**Interfaces:**
- Consumes: `useInterviewTemplates`, `InterviewTemplate` (Task 5); `useJob`.
- Produces: `ScheduleRoundDialog`; `useInterviewKit(...).templateName: string | null`; `markScheduled(templateId?: number | null)` and `reopenRound(templateId?: number | null)` — `undefined` sends no `interview_template_id` (the server then uses the job's default), a number or `null` sends it explicitly.

- [ ] **Step 1: Mutations accept the template**

In `src/hooks/use-application-mutations.ts`, add `interview_template_id?: number | null;` to `PatchPayload`, and replace `markScheduled` / `reopenRound` with:

```ts
    // `undefined` omits interview_template_id so the server applies the
    // job's default; a number or null is sent as an explicit choice.
    markScheduled: (templateId?: number | null) =>
      patch.mutate(templateId === undefined
        ? { stage: "scheduled" }
        : { stage: "scheduled", interview_template_id: templateId }),
    reopenRound: (templateId?: number | null) =>
      patch.mutate(templateId === undefined
        ? { stage: "scheduled" }
        : { stage: "scheduled", interview_template_id: templateId }),
```

- [ ] **Step 2: Write the failing dialog test**

Create `src/components/candidate/schedule-round-dialog.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ScheduleRoundDialog } from "./schedule-round-dialog";

const T = (id: number, name: string) => ({
  id, name, description: null, questions: [], probe_mode: "none" as const,
  include_job_questions: false, is_active: true,
});

describe("ScheduleRoundDialog", () => {
  it("preselects the job's default and confirms it", async () => {
    const onConfirm = vi.fn();
    render(<ScheduleRoundDialog open onOpenChange={() => {}} title="Schedule interview"
      templates={[T(1, "Technical"), T(2, "RH screen")]} defaultTemplateId={2}
      onConfirm={onConfirm} />);

    expect(screen.getByRole("combobox")).toHaveTextContent("RH screen");
    await userEvent.click(screen.getByRole("button", { name: /^schedule$/i }));
    expect(onConfirm).toHaveBeenCalledWith(2);
  });

  it("offers No template, confirmed as null", async () => {
    const onConfirm = vi.fn();
    render(<ScheduleRoundDialog open onOpenChange={() => {}} title="Schedule interview"
      templates={[T(1, "Technical")]} defaultTemplateId={null} onConfirm={onConfirm} />);

    expect(screen.getByRole("combobox")).toHaveTextContent(/no template/i);
    await userEvent.click(screen.getByRole("button", { name: /^schedule$/i }));
    expect(onConfirm).toHaveBeenCalledWith(null);
  });

  it("does not preselect a default that is not among the active templates", () => {
    render(<ScheduleRoundDialog open onOpenChange={() => {}} title="Schedule interview"
      templates={[T(1, "Technical")]} defaultTemplateId={99} onConfirm={() => {}} />);
    expect(screen.getByRole("combobox")).toHaveTextContent(/no template/i);
  });
});
```

Run: `npx vitest --run src/components/candidate/schedule-round-dialog.test.tsx` — expected FAIL (module missing).

- [ ] **Step 3: Build the dialog**

Create `src/components/candidate/schedule-round-dialog.tsx` using `Dialog` from `@/components/ui/dialog` and Radix `Select`:

```tsx
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import type { InterviewTemplate } from "@/hooks/use-interview-templates";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** Active templates only. */
  templates: InterviewTemplate[];
  defaultTemplateId: number | null;
  onConfirm: (templateId: number | null) => void;
  pending?: boolean;
}

const NONE = "none";

export function ScheduleRoundDialog({
  open, onOpenChange, title, templates, defaultTemplateId, onConfirm, pending,
}: Props) {
  // A default that is archived or unknown is never preselected.
  const initial = templates.some((t) => t.id === defaultTemplateId)
    ? String(defaultTemplateId) : NONE;
  const [choice, setChoice] = useState(initial);
  useEffect(() => { if (open) setChoice(initial); }, [open, initial]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            The template decides which questions this round asks and whether any are generated.
          </DialogDescription>
        </DialogHeader>
        <Select value={choice} onValueChange={setChoice}>
          <SelectTrigger aria-label="Interview template"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE}>No template — the job's own questions</SelectItem>
            {templates.map((t) => (
              <SelectItem key={t.id} value={String(t.id)}>{t.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={pending}
            onClick={() => onConfirm(choice === NONE ? null : Number(choice))}>
            Schedule
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

Run the dialog test — expected PASS.

- [ ] **Step 4: Wire it into the action bar**

In `src/components/candidate/action-bar.tsx`:
- read `const templates = useInterviewTemplates(false).data ?? [];` and `const job = useJob(application.job_id);` (`useJob` is in `@/hooks/use-job`);
- add state `const [pickerFor, setPickerFor] = useState<"schedule" | "reopen" | null>(null);`
- the two buttons today pass the mutation straight through (`onClick={m.markScheduled}`, `onClick={m.reopenRound}`). That is now a bug: the functions take a template id, and `onClick` would hand them the click event as one. Replace both with explicit handlers:

```tsx
  // With no templates the picker would offer only "No template", so skip
  // it: one click, exactly as before templates existed. A click before the
  // list has loaded also lands here, and omitting the field makes the
  // server use the job's default, which is the safe choice.
  const startSchedule = () =>
    templates.length === 0 ? m.markScheduled() : setPickerFor("schedule");
  const startReopen = () =>
    templates.length === 0 ? m.reopenRound() : setPickerFor("reopen");
```

  and use `onClick={startSchedule}` on "Mark as scheduled" and `onClick={startReopen}` on "Another round";
- render once, after `RejectDialog`:

```tsx
      <ScheduleRoundDialog
        open={pickerFor !== null}
        onOpenChange={(o) => { if (!o) setPickerFor(null); }}
        title={pickerFor === "reopen" ? "Start another round" : "Schedule interview"}
        templates={templates}
        defaultTemplateId={job.data?.default_interview_template_id ?? null}
        pending={m.isPending}
        onConfirm={(templateId) => {
          if (pickerFor === "reopen") m.reopenRound(templateId); else m.markScheduled(templateId);
          setPickerFor(null);
        }}
      />
```

`action-bar.test.tsx` mocks `@/lib/api` with a single `apiMock` resolving `{}` for every call, and its "offers another interview round" test reads the PATCH as `apiMock.mock.calls[0]`. The bar now also fetches templates and the job on mount, so the PATCH is no longer call 0, and `{}` is not a template list. Make exactly these two harness changes:

1. The `beforeEach` mock returns a list for the templates path:

```ts
beforeEach(() => {
  apiMock.mockReset();
  apiMock.mockImplementation(async (path: string) =>
    path.startsWith("/api/interview-templates") ? [] : {});
});
```

2. In "offers another interview round", replace the two lines

```ts
    await waitFor(() => expect(apiMock).toHaveBeenCalled());
    const [path, opts] = apiMock.mock.calls[0];
```

with

```ts
    const isPatch = ([, o]: unknown[]) => (o as { method?: string } | undefined)?.method === "PATCH";
    await waitFor(() => expect(apiMock.mock.calls.some(isPatch)).toBe(true));
    const [path, opts] = apiMock.mock.calls.find(isPatch)!;
```

Leave the `expect(path)…` and `expect(opts)…` lines after it untouched. With no templates, both buttons must still send exactly `{ stage: "scheduled" }`, and those unchanged expectations are what prove it.

Then add this test. The templates are seeded into the query cache before render, so the click cannot race the fetch:

```tsx
  it("opens the template picker instead of scheduling when templates exist", async () => {
    const technical = { id: 1, name: "Technical", description: null, questions: [],
                        probe_mode: "score_gaps", include_job_questions: true, is_active: true };
    apiMock.mockImplementation(async (path: string) =>
      path.startsWith("/api/interview-templates") ? [technical] : {});
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    qc.setQueryData(queryKeys.interviewTemplates(false), [technical]);
    render(
      <QueryClientProvider client={qc}>
        <ActionBar application={baseApp({ stage: "invited" })} candidateEmail="alice@example.com" />
      </QueryClientProvider>,
    );

    await userEvent.click(screen.getByRole("button", { name: /mark as scheduled/i }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(apiMock.mock.calls.some(([, o]) => o?.method === "PATCH")).toBe(false);
  });
```

(add `import { queryKeys } from "@/lib/query-keys";` to the test's imports).

`src/routes/application-detail.test.tsx` renders the action bar through the page with msw set to `onUnhandledRequest: "error"`. Add one handler to its `setupServer(...)` list, beside the existing `http.get(".../api/jobs/6", …)`:

```ts
  http.get("http://localhost:8000/api/interview-templates", () => HttpResponse.json([])),
```

- [ ] **Step 5: The kit header names its template**

In `src/hooks/use-interview-kit.ts`, add `template_name?: string | null;` to `KitResponse` and return it from the hook as `templateName: query.data?.template_name ?? null` alongside `kit` and `sheets`.

In `src/components/candidate/interview-kit-section.tsx`, destructure `templateName` from `useInterviewKit(applicationId)`. The main render's header (the `<section className="space-y-3">` return near the end, not the four early-return states) is currently:

```tsx
      <h3 className="text-lg font-semibold">
        Interview kit
        {(interviewRound ?? 1) > 1 && (
          <span className="ml-2 text-xs font-normal uppercase tracking-[0.18em] text-muted-foreground">
            Round {interviewRound}
          </span>
        )}
      </h3>
```

Replace it with:

```tsx
      <h3 className="text-lg font-semibold">
        Interview kit
        {headerLabel && (
          <span className="ml-2 text-xs font-normal uppercase tracking-[0.18em] text-muted-foreground">
            {headerLabel}
          </span>
        )}
      </h3>
```

with, just above that `return`:

```tsx
  // "Round 2 · RH screen". The round is labelled only past the first, as
  // before; the template whenever the kit was built from one.
  const headerLabel = [
    (interviewRound ?? 1) > 1 ? `Round ${interviewRound}` : null,
    templateName,
  ].filter(Boolean).join(" · ");
```

With no template the label is exactly "Round N" or nothing, as today.

The test, in `interview-kit-section.test.tsx` (write it before touching the component): `mountWithKit(kit, capture, opts)` serves `{ kit, sheets }` from its GET handler. Add `templateName?: string` to its `opts` type and change that one handler to

```ts
    http.get("http://localhost:8000/api/applications/1/interview-kit", () =>
      HttpResponse.json({ kit, sheets: opts.sheets ?? [], template_name: opts.templateName ?? null })),
```

then add:

```tsx
  it("names the template the round was built from", async () => {
    mountWithKit(
      { status: "ready", questions: [{ id: "q1", text: "Why us?", source: "baseline",
                                       answer: null, rating: null }] },
      {},
      { interviewRound: 2, templateName: "RH screen" },
    );
    expect(await screen.findByText("Round 2 · RH screen")).toBeInTheDocument();
  });
```

Run it before the component change and expect FAIL, since the header shows only "Round 2". It should PASS after the change.

- [ ] **Step 6: Verify and commit**

Run: `npx vitest --run`, `npm run lint`, `npm run build` — all pass.
Run: `uv run pytest -q` (timeout 400000) — still all pass (no backend change in this task).

```bash
git add recruiter-frontend/src
git commit -m "feat(interview-kit): pick a template when a round starts

Mark as scheduled and Another round open a picker with every active
template, the job's default preselected, plus No template. With no
templates defined the picker never appears and both buttons stay a
single click. The kit header names the template the round was built from.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```
