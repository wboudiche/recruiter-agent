# Multiple Interviewers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let several users interview one candidate, each on their own feedback sheet over a shared question kit, with the candidate moving to `INTERVIEWED` once every sheet is submitted.

**Architecture:** A new `interview_assignments` table holds one row per (application, interviewer) with the interviewer's sheet as JSON; the shared questions stay in `applications.interview_kit`. Sheet routes sit beside the existing kit routes in `api/interview.py`; assignment routes get their own router. Pure rules (visibility, freeze, all-submitted) live in `pipeline/interview_sheets.py` so they are unit-testable without a database. The frontend swaps per-question answers for a per-caller sheet and adds a picker, a verdict block, and a side-by-side feedback table.

**Tech Stack:** FastAPI + SQLAlchemy 2 async + Alembic + Pydantic v2 (backend, `uv run pytest`); React 18 + TanStack Query + vitest + Playwright (frontend, `npx vitest --run`, `npx playwright test`).

**Spec:** `docs/superpowers/specs/2026-09-14-multi-interviewer-design.md`

## Global Constraints

- Backend tests run against a real Postgres via testcontainers: `uv run pytest tests/api/<file> -q`. The `api_client` fixture logs in a dev-bypass admin (`test-user@acme.com`); role tests use `api_client_unauth` + `db_session_with_schema` and the `_add`/`_login` helpers copied into each test module (`tests` is not an importable package — never `from tests.… import`).
- Frontend tests: `cd recruiter-frontend && npx vitest --run <file>`; types: `npx tsc --noEmit`.
- Commit subjects use the repo's prefixes: `feat(interview-kit):`, `test(interview-kit):`, `ui(interview-kit):`, `sec(permissions):`, `docs(…)`.
- Every commit ends with the attribution trailer given in the session's system reminder.
- Per-row controls get accessible names keyed on row index (`Question ${i+1}`), never on mutable text (decisions doc).
- The app is permanently dark-themed: never rely on `dark:` variants; light surfaces need explicit dark text.
- Free-text limits: 20 000 chars per answer, 2 000 for the verdict note, 2 000 per question (`schemas/interview.py`).
- Ratings enum is exactly `strong | adequate | weak`; verdict decision is exactly `hire | no_hire | unsure`.
- No route-local `require_role` on interview routes except where this plan says so; the app-wide `viewer_readonly_guard` is the default gate.

---

## File map

| File | Responsibility |
|---|---|
| `alembic/versions/20260914_000000_interview_assignments.py` | create `interview_assignments` |
| `src/recruiter/models/interview_assignment.py` | `InterviewAssignment` ORM model |
| `src/recruiter/models/__init__.py` | export it |
| `src/recruiter/schemas/interview.py` | `SheetAnswer`, `Verdict`, `InterviewSheet`, `SheetRead`, `KitQuestion.added_by`, `InterviewKit.closed_at` |
| `src/recruiter/pipeline/interview_sheets.py` | pure rules: `visible_sheets`, `is_frozen`, `all_submitted`, `prune_answers` |
| `src/recruiter/api/interviewers.py` | `GET/PUT /api/applications/{id}/interviewers` |
| `src/recruiter/api/users.py` | `GET /api/users/directory` |
| `src/recruiter/api/interview.py` | kit GET gains `sheets`; sheet PATCH/submit; freeze on PATCH/generate; legacy submit route removed |
| `src/recruiter/api/applications.py` | `closed_at` on manual move; `sheets_total`/`sheets_submitted` on reads |
| `src/recruiter/api/permissions.py` | viewer allow-list + docstring |
| `src/recruiter/main.py` | register the interviewers router |
| `recruiter-frontend/src/hooks/use-interview-kit.ts` | sheet types and mutations |
| `recruiter-frontend/src/hooks/use-interviewers.ts` | assignments + user directory |
| `recruiter-frontend/src/lib/query-keys.ts`, `src/lib/sse.ts` | new keys; invalidation on `interview_kit` events |
| `recruiter-frontend/src/components/candidate/interviewers-picker.tsx` | chips + assign dialog |
| `recruiter-frontend/src/components/candidate/interview-kit-section.tsx` | sheet-based answers, verdict, submit dialog, freeze, legacy |
| `recruiter-frontend/src/components/candidate/feedback-table.tsx` | side-by-side ratings |
| `recruiter-frontend/src/components/kanban/candidate-card.tsx` | `n/m sheets in` badge |
| `recruiter-frontend/e2e/interview-kit.spec.ts` | two-interviewer flow |

---

### Task 1: Migration, model, schemas

**Files:**
- Create: `alembic/versions/20260914_000000_interview_assignments.py`
- Create: `src/recruiter/models/interview_assignment.py`
- Modify: `src/recruiter/models/__init__.py`
- Modify: `src/recruiter/schemas/interview.py`
- Test: `tests/unit/test_interview_assignment_model.py`, `tests/unit/test_interview_schemas.py`

**Interfaces:**
- Produces: `InterviewAssignment(application_id, user_id, sheet: dict, submitted_at: datetime|None)` with `__tablename__ = "interview_assignments"` and unique `(application_id, user_id)`.
- Produces: `InterviewSheet(answers: dict[str, SheetAnswer], verdict: Verdict)`, `SheetAnswer(answer: str|None, rating: Rating|None)`, `Verdict(decision: Literal["hire","no_hire","unsure"]|None, note: str|None)`, `SheetRead(user_id, name, email, sheet, submitted_at)`; `KitQuestion.added_by: int|None`; `InterviewKit.closed_at: str|None`.

- [ ] **Step 1: Write the failing model test**

`tests/unit/test_interview_assignment_model.py`:

```python
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.models import (
    Application, Candidate, InterviewAssignment, Job, Role, Stage, User,
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_interview_assignment_model.py -q`
Expected: FAIL with `ImportError: cannot import name 'InterviewAssignment'`

- [ ] **Step 3: Write the model**

`src/recruiter/models/interview_assignment.py`:

```python
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


def empty_sheet() -> dict:
    return {"answers": {}, "verdict": {"decision": None, "note": None}}


class InterviewAssignment(Base):
    """One interviewer on one application, with their feedback sheet.

    Questions are shared and live in `applications.interview_kit`; only the
    answers, ratings and verdict are per person. Each interviewer writes
    their own row, so two people saving at once never overwrite each other.
    """

    __tablename__ = "interview_assignments"
    __table_args__ = (
        UniqueConstraint("application_id", "user_id", name="uq_interview_assignment_app_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    sheet: Mapped[dict] = mapped_column(JSON, nullable=False, default=empty_sheet)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
```

Add to `src/recruiter/models/__init__.py`:

```python
from recruiter.models.interview_assignment import InterviewAssignment
```

and `"InterviewAssignment",` to `__all__` (alphabetical, after `"EventLog"`).

- [ ] **Step 4: Write the migration**

`alembic/versions/20260914_000000_interview_assignments.py`:

```python
"""add interview_assignments: one feedback sheet per interviewer per application

Revision ID: a7d2c4f19e58
Revises: c4e1a90b7d32
Create Date: 2026-09-14 00:00:00.000000

Questions stay in applications.interview_kit (shared); this table holds
who interviews and their own answers/ratings/verdict. No data migration:
legacy per-question answers in the kit JSON are read but never written
again (see docs/superpowers/specs/2026-09-14-multi-interviewer-design.md).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a7d2c4f19e58'
down_revision: Union[str, None] = 'c4e1a90b7d32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "interview_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("application_id", sa.Integer(),
                  sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sheet", sa.JSON(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("application_id", "user_id",
                            name="uq_interview_assignment_app_user"),
    )
    op.create_index("ix_interview_assignments_application_id",
                    "interview_assignments", ["application_id"])
    op.create_index("ix_interview_assignments_user_id",
                    "interview_assignments", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_interview_assignments_user_id", table_name="interview_assignments")
    op.drop_index("ix_interview_assignments_application_id", table_name="interview_assignments")
    op.drop_table("interview_assignments")
```

- [ ] **Step 5: Run the model test to verify it passes**

Run: `uv run pytest tests/unit/test_interview_assignment_model.py -q`
Expected: 3 passed

- [ ] **Step 6: Write the failing schema test**

`tests/unit/test_interview_schemas.py`:

```python
import pytest
from pydantic import ValidationError

from recruiter.schemas.interview import InterviewKit, InterviewSheet, KitQuestion


def test_sheet_defaults_are_empty() -> None:
    sheet = InterviewSheet()
    assert sheet.answers == {}
    assert sheet.verdict.decision is None
    assert sheet.verdict.note is None


def test_sheet_accepts_answers_keyed_by_question_id() -> None:
    sheet = InterviewSheet.model_validate({
        "answers": {"q1": {"answer": "Ran it for two years.", "rating": "strong"}},
        "verdict": {"decision": "hire", "note": "Solid."},
    })
    assert sheet.answers["q1"].rating == "strong"
    assert sheet.verdict.decision == "hire"


def test_sheet_rejects_unknown_rating_and_decision() -> None:
    with pytest.raises(ValidationError):
        InterviewSheet.model_validate({"answers": {"q1": {"answer": None, "rating": "great"}}})
    with pytest.raises(ValidationError):
        InterviewSheet.model_validate({"verdict": {"decision": "maybe", "note": None}})


def test_kit_question_added_by_and_kit_closed_at_default_to_none() -> None:
    q = KitQuestion(id="q1", text="Why?", source="probe")
    assert q.added_by is None
    kit = InterviewKit(status="ready")
    assert kit.closed_at is None
```

- [ ] **Step 7: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_interview_schemas.py -q`
Expected: FAIL with `ImportError: cannot import name 'InterviewSheet'`

- [ ] **Step 8: Extend the schemas**

In `src/recruiter/schemas/interview.py`, add `added_by` to `KitQuestion`, `closed_at` to `InterviewKit`, and the sheet models after `InterviewKit`:

```python
class KitQuestion(_TextQuestion):
    source: QuestionSource
    # Legacy: answers and ratings now live on each interviewer's sheet
    # (InterviewSheet). These two are read for kits recorded before that
    # change and never written again.
    answer: str | None = Field(default=None, max_length=20000)
    rating: Rating | None = None
    # User id of the interviewer who appended the question; None for
    # generated and recruiter-authored questions.
    added_by: int | None = None


class InterviewKit(BaseModel):
    status: KitStatus
    error: str | None = None
    generated_at: str | None = None
    # Legacy single-submit timestamp; see KitQuestion.answer.
    submitted_at: str | None = None
    # Set when the candidate moves to INTERVIEWED, by the all-sheets-in
    # rule or the recruiter's manual move.
    closed_at: str | None = None
    questions: list[KitQuestion] = Field(default_factory=list)


VerdictDecision = Literal["hire", "no_hire", "unsure"]


class SheetAnswer(BaseModel):
    answer: str | None = Field(default=None, max_length=20000)
    rating: Rating | None = None


class Verdict(BaseModel):
    decision: VerdictDecision | None = None
    note: str | None = Field(default=None, max_length=2000)


class InterviewSheet(BaseModel):
    """One interviewer's feedback over the shared kit, keyed by question id."""

    answers: dict[str, SheetAnswer] = Field(default_factory=dict)
    verdict: Verdict = Field(default_factory=Verdict)


class SheetRead(BaseModel):
    user_id: int
    name: str | None
    email: str
    sheet: InterviewSheet
    submitted_at: str | None
```

- [ ] **Step 9: Run both test files and the existing interview tests**

Run: `uv run pytest tests/unit/test_interview_schemas.py tests/unit/test_interview_assignment_model.py tests/unit/test_interview_kit.py tests/api/test_interview_api.py -q`
Expected: all pass (existing tests unaffected: new fields default to None)

- [ ] **Step 10: Commit**

```bash
git add alembic/versions/20260914_000000_interview_assignments.py src/recruiter/models/interview_assignment.py src/recruiter/models/__init__.py src/recruiter/schemas/interview.py tests/unit/test_interview_assignment_model.py tests/unit/test_interview_schemas.py
git commit -m "feat(interview-kit): interview_assignments table and sheet schemas"
```

---

### Task 2: Pure sheet rules

**Files:**
- Create: `src/recruiter/pipeline/interview_sheets.py`
- Test: `tests/unit/test_interview_sheets_rules.py`

**Interfaces:**
- Produces:
  - `is_frozen(rows: Iterable[InterviewAssignment]) -> bool` — any row submitted.
  - `all_submitted(rows) -> bool` — non-empty and every row submitted.
  - `visible_sheets(rows, *, user: User) -> list[InterviewAssignment]` — the visibility table.
  - `prune_answers(sheet: InterviewSheet, question_ids: set[str]) -> InterviewSheet` — drop answers for unknown ids.
  - `can_edit_questions(user: User) -> bool` — recruiter or admin.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_interview_sheets_rules.py`:

```python
from datetime import UTC, datetime

from recruiter.models import InterviewAssignment, Role, User
from recruiter.pipeline.interview_sheets import (
    all_submitted, can_edit_questions, is_frozen, prune_answers, visible_sheets,
)
from recruiter.schemas.interview import InterviewSheet


def _user(uid: int, role: Role) -> User:
    u = User(email=f"u{uid}@acme.com", role=role, is_active=True)
    u.id = uid
    return u


def _row(uid: int, submitted: bool) -> InterviewAssignment:
    return InterviewAssignment(
        application_id=1, user_id=uid, sheet={},
        submitted_at=datetime.now(UTC) if submitted else None,
    )


def test_frozen_once_any_sheet_is_submitted() -> None:
    assert not is_frozen([])
    assert not is_frozen([_row(1, False), _row(2, False)])
    assert is_frozen([_row(1, False), _row(2, True)])


def test_all_submitted_requires_every_row_and_at_least_one() -> None:
    assert not all_submitted([])
    assert not all_submitted([_row(1, True), _row(2, False)])
    assert all_submitted([_row(1, True), _row(2, True)])


def test_recruiter_and_admin_see_every_sheet() -> None:
    rows = [_row(1, False), _row(2, True)]
    assert visible_sheets(rows, user=_user(9, Role.RECRUITER)) == rows
    assert visible_sheets(rows, user=_user(9, Role.ADMIN)) == rows


def test_assigned_interviewer_sees_only_own_sheet_until_submitted() -> None:
    rows = [_row(1, False), _row(2, True)]
    assert visible_sheets(rows, user=_user(1, Role.VIEWER)) == [rows[0]]


def test_assigned_interviewer_sees_all_after_own_submit() -> None:
    rows = [_row(1, True), _row(2, False)]
    assert visible_sheets(rows, user=_user(1, Role.VIEWER)) == rows


def test_unassigned_viewer_sees_no_sheets() -> None:
    rows = [_row(1, True), _row(2, True)]
    assert visible_sheets(rows, user=_user(3, Role.VIEWER)) == []


def test_prune_drops_answers_for_questions_no_longer_in_kit() -> None:
    sheet = InterviewSheet.model_validate({
        "answers": {"keep": {"answer": "a", "rating": None}, "gone": {"answer": "b", "rating": None}},
    })
    pruned = prune_answers(sheet, {"keep"})
    assert set(pruned.answers) == {"keep"}


def test_only_recruiters_and_admins_edit_questions() -> None:
    assert can_edit_questions(_user(1, Role.ADMIN))
    assert can_edit_questions(_user(1, Role.RECRUITER))
    assert not can_edit_questions(_user(1, Role.VIEWER))
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_interview_sheets_rules.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'recruiter.pipeline.interview_sheets'`

- [ ] **Step 3: Implement**

`src/recruiter/pipeline/interview_sheets.py`:

```python
"""Rules for interviewer sheets, kept free of I/O so they are trivially testable.

Design: docs/superpowers/specs/2026-09-14-multi-interviewer-design.md.
"""
from collections.abc import Iterable

from recruiter.models import InterviewAssignment, Role, User
from recruiter.schemas.interview import InterviewSheet


def is_frozen(rows: Iterable[InterviewAssignment]) -> bool:
    """Once any sheet is submitted the question list must not lose rows,
    or submitted feedback would silently lose its answers."""
    return any(r.submitted_at is not None for r in rows)


def all_submitted(rows: Iterable[InterviewAssignment]) -> bool:
    rows = list(rows)
    return bool(rows) and all(r.submitted_at is not None for r in rows)


def can_edit_questions(user: User) -> bool:
    return user.role in (Role.ADMIN, Role.RECRUITER)


def visible_sheets(
    rows: Iterable[InterviewAssignment], *, user: User,
) -> list[InterviewAssignment]:
    """Blind until submitted: an interviewer sees only their own sheet until
    they submit, then everyone's. Recruiters and admins always see all;
    an unassigned viewer sees none."""
    rows = list(rows)
    if can_edit_questions(user):
        return rows
    own = next((r for r in rows if r.user_id == user.id), None)
    if own is None:
        return []
    if own.submitted_at is None:
        return [own]
    return rows


def prune_answers(sheet: InterviewSheet, question_ids: set[str]) -> InterviewSheet:
    """Drop answers for questions no longer in the kit. Dropping rather than
    rejecting means a recruiter removing a question while an interviewer is
    typing does not turn the interviewer's save into an error."""
    return sheet.model_copy(update={
        "answers": {k: v for k, v in sheet.answers.items() if k in question_ids},
    })
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_interview_sheets_rules.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/pipeline/interview_sheets.py tests/unit/test_interview_sheets_rules.py
git commit -m "feat(interview-kit): pure rules for interviewer sheets"
```

---

### Task 3: Assignments API and user directory

**Files:**
- Create: `src/recruiter/api/interviewers.py`
- Modify: `src/recruiter/api/users.py` (add `GET /api/users/directory`)
- Modify: `src/recruiter/main.py:11,100` (import + `_api_router.include_router(interviewers.router)`)
- Test: `tests/api/test_interviewers_api.py`

**Interfaces:**
- Produces: `GET /api/applications/{id}/interviewers -> list[InterviewerRead]` where `InterviewerRead(user_id, name, email, submitted_at)`.
- Produces: `PUT /api/applications/{id}/interviewers` body `{"user_ids": [int]}`, response `list[InterviewerRead]`; 409 on removing a submitted sheet, 422 on unknown/inactive user.
- Produces: `GET /api/users/directory -> list[UserDirectoryRead]` where `UserDirectoryRead(id, name, email, role)`, active users only, recruiter or admin.
- Produces: helper `load_assignments(session, application_id) -> list[InterviewAssignment]` (ordered by `created_at, id`) reused by Task 4.

- [ ] **Step 1: Write the failing tests**

`tests/api/test_interviewers_api.py`:

```python
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recruiter.api.candidates import get_engine_dep
from recruiter.auth.passwords import hash_password
from recruiter.main import app
from recruiter.models import Application, Candidate, InterviewAssignment, Job, Role, Stage, User


async def _add(session: AsyncSession, email: str, role: Role, active: bool = True) -> User:
    user = User(email=email, role=role, is_active=active,
                password_hash=hash_password("pw-12345678"))
    session.add(user)
    await session.commit()
    return user


async def _login(client: AsyncClient, email: str) -> None:
    r = await client.post("/api/auth/login/password",
                           json={"email": email, "password": "pw-12345678"})
    assert r.status_code == 204


async def _seed_application(session: AsyncSession) -> int:
    job = Job(title="Backend", description="x", criteria=[])
    session.add(job)
    await session.flush()
    candidate = Candidate(source_type="paste", full_name="Marie", email="m@example.com")
    session.add(candidate)
    await session.flush()
    app_row = Application(job_id=job.id, candidate_id=candidate.id, stage=Stage.SCHEDULED)
    session.add(app_row)
    await session.commit()
    return app_row.id


def _sessionmaker():
    return async_sessionmaker(app.dependency_overrides[get_engine_dep](), expire_on_commit=False)


async def _add_user_via_engine(email: str, role: Role, active: bool = True) -> int:
    async with _sessionmaker()() as session:
        return (await _add(session, email, role, active)).id


@pytest.mark.asyncio
async def test_put_creates_then_removes_assignments(api_client: AsyncClient, create_scored_app) -> None:
    app_id = await create_scored_app()
    a = await _add_user_via_engine("a@acme.com", Role.VIEWER)
    b = await _add_user_via_engine("b@acme.com", Role.RECRUITER)

    put = await api_client.put(f"/api/applications/{app_id}/interviewers", json={"user_ids": [a, b]})
    assert put.status_code == 200
    assert [r["user_id"] for r in put.json()] == [a, b]
    assert put.json()[0]["email"] == "a@acme.com"
    assert put.json()[0]["submitted_at"] is None

    put = await api_client.put(f"/api/applications/{app_id}/interviewers", json={"user_ids": [b]})
    assert [r["user_id"] for r in put.json()] == [b]

    get = await api_client.get(f"/api/applications/{app_id}/interviewers")
    assert [r["user_id"] for r in get.json()] == [b]


@pytest.mark.asyncio
async def test_put_is_idempotent(api_client: AsyncClient, create_scored_app) -> None:
    app_id = await create_scored_app()
    a = await _add_user_via_engine("a@acme.com", Role.VIEWER)
    for _ in range(2):
        r = await api_client.put(f"/api/applications/{app_id}/interviewers", json={"user_ids": [a]})
        assert r.status_code == 200
    assert len((await api_client.get(f"/api/applications/{app_id}/interviewers")).json()) == 1


@pytest.mark.asyncio
async def test_put_refuses_removing_a_submitted_sheet(api_client: AsyncClient, create_scored_app) -> None:
    from datetime import UTC, datetime
    app_id = await create_scored_app()
    a = await _add_user_via_engine("a@acme.com", Role.VIEWER)
    async with _sessionmaker()() as session:
        session.add(InterviewAssignment(application_id=app_id, user_id=a,
                                        submitted_at=datetime.now(UTC)))
        await session.commit()
    r = await api_client.put(f"/api/applications/{app_id}/interviewers", json={"user_ids": []})
    assert r.status_code == 409
    assert "submitted" in r.json()["detail"]


@pytest.mark.asyncio
async def test_put_rejects_unknown_and_inactive_users(api_client: AsyncClient, create_scored_app) -> None:
    app_id = await create_scored_app()
    inactive = await _add_user_via_engine("gone@acme.com", Role.VIEWER, active=False)
    r = await api_client.put(f"/api/applications/{app_id}/interviewers", json={"user_ids": [999999]})
    assert r.status_code == 422
    r = await api_client.put(f"/api/applications/{app_id}/interviewers", json={"user_ids": [inactive]})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_put_404s_for_unknown_application(api_client: AsyncClient) -> None:
    r = await api_client.put("/api/applications/999999/interviewers", json={"user_ids": []})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_viewer_can_list_but_not_assign(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_id = await _seed_application(db_session_with_schema)
    await _add(db_session_with_schema, "viewer@acme.com", Role.VIEWER)
    await _login(api_client_unauth, "viewer@acme.com")
    assert (await api_client_unauth.get(f"/api/applications/{app_id}/interviewers")).status_code == 200
    r = await api_client_unauth.put(f"/api/applications/{app_id}/interviewers", json={"user_ids": []})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_directory_lists_active_users_for_recruiters_only(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    await _add(db_session_with_schema, "rec@acme.com", Role.RECRUITER)
    await _add(db_session_with_schema, "viewer@acme.com", Role.VIEWER)
    await _add(db_session_with_schema, "gone@acme.com", Role.VIEWER, active=False)

    await _login(api_client_unauth, "rec@acme.com")
    r = await api_client_unauth.get("/api/users/directory")
    assert r.status_code == 200
    emails = [u["email"] for u in r.json()]
    assert "gone@acme.com" not in emails
    assert {"rec@acme.com", "viewer@acme.com"} <= set(emails)
    assert set(r.json()[0]) == {"id", "name", "email", "role"}

    await api_client_unauth.post("/api/auth/logout")
    await _login(api_client_unauth, "viewer@acme.com")
    assert (await api_client_unauth.get("/api/users/directory")).status_code == 403
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/api/test_interviewers_api.py -q`
Expected: FAIL — 404s on the interviewers routes and the directory route (routes do not exist)

- [ ] **Step 3: Add the directory endpoint**

In `src/recruiter/schemas/user.py`, after `UserAdminRead`:

```python
class UserDirectoryRead(BaseModel):
    """What a recruiter may see about colleagues when picking interviewers.
    No activity or login data — that stays on the admin projection."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None
    email: str
    role: Role
```

In `src/recruiter/api/users.py`, import `UserDirectoryRead` and add **before** any route with a path parameter:

```python
@router.get("/directory", response_model=list[UserDirectoryRead])
async def user_directory(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(Role.ADMIN, Role.RECRUITER)),
) -> list[UserDirectoryRead]:
    """Active users, for assigning interviewers. Recruiter or admin: the
    picker is a recruiter action, and viewers have no reason to enumerate
    accounts."""
    rows = (await session.execute(
        select(User).where(User.is_active.is_(True)).order_by(User.email)
    )).scalars().all()
    return [UserDirectoryRead.model_validate(r) for r in rows]
```

- [ ] **Step 4: Write the assignments router**

`src/recruiter/api/interviewers.py`:

```python
"""Who interviews which candidate.

One row per (application, user) in `interview_assignments`; the sheet on
each row is written through `api/interview.py`. Assigning is a recruiter
action; listing is open to every role so an interviewer can see who else
is on the panel.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.candidates import get_event_bus
from recruiter.api.deps import get_session, require_role, require_user
from recruiter.events import EventBus
from recruiter.models import Application, InterviewAssignment, Role, User

router = APIRouter(prefix="/api", tags=["interview"], dependencies=[Depends(require_user)])


class InterviewerRead(BaseModel):
    user_id: int
    name: str | None
    email: str
    submitted_at: str | None


class InterviewersPut(BaseModel):
    user_ids: list[int]


async def load_assignments(session: AsyncSession, application_id: int) -> list[InterviewAssignment]:
    return list((await session.execute(
        select(InterviewAssignment)
        .where(InterviewAssignment.application_id == application_id)
        .order_by(InterviewAssignment.created_at, InterviewAssignment.id)
    )).scalars().all())


async def _read_all(session: AsyncSession, application_id: int) -> list[InterviewerRead]:
    rows = await load_assignments(session, application_id)
    users = {u.id: u for u in (await session.execute(
        select(User).where(User.id.in_([r.user_id for r in rows] or [-1]))
    )).scalars().all()}
    return [
        InterviewerRead(
            user_id=r.user_id,
            name=users[r.user_id].name,
            email=users[r.user_id].email,
            submitted_at=r.submitted_at.isoformat() if r.submitted_at else None,
        )
        for r in rows
    ]


@router.get("/applications/{application_id}/interviewers", response_model=list[InterviewerRead])
async def list_interviewers(
    application_id: int, session: AsyncSession = Depends(get_session),
) -> list[InterviewerRead]:
    if await session.get(Application, application_id) is None:
        raise HTTPException(status_code=404, detail="application not found")
    return await _read_all(session, application_id)


@router.put("/applications/{application_id}/interviewers", response_model=list[InterviewerRead])
async def put_interviewers(
    application_id: int,
    payload: InterviewersPut,
    session: AsyncSession = Depends(get_session),
    bus: EventBus = Depends(get_event_bus),
    _: User = Depends(require_role(Role.ADMIN, Role.RECRUITER)),
) -> list[InterviewerRead]:
    """Reconcile to exactly `user_ids`: create missing rows, delete the rest.
    Refuses to delete a submitted sheet — feedback must not vanish by
    unticking a name."""
    if await session.get(Application, application_id) is None:
        raise HTTPException(status_code=404, detail="application not found")

    wanted = list(dict.fromkeys(payload.user_ids))  # dedupe, keep order
    if wanted:
        found = {u.id for u in (await session.execute(
            select(User).where(User.id.in_(wanted), User.is_active.is_(True))
        )).scalars().all()}
        missing = [uid for uid in wanted if uid not in found]
        if missing:
            raise HTTPException(status_code=422, detail=f"unknown or inactive users: {missing}")

    existing = await load_assignments(session, application_id)
    by_user = {r.user_id: r for r in existing}
    for row in existing:
        if row.user_id not in wanted:
            if row.submitted_at is not None:
                raise HTTPException(
                    status_code=409,
                    detail="cannot remove an interviewer whose sheet is submitted",
                )
            await session.delete(row)
    for uid in wanted:
        if uid not in by_user:
            session.add(InterviewAssignment(application_id=application_id, user_id=uid))
    await session.commit()
    # Same event the kit uses, so any open candidate page refetches its
    # interviewer chips and sheets (see lib/sse.ts).
    await bus.publish({
        "type": "interview_kit", "application_id": application_id, "status": "ready",
    })
    return await _read_all(session, application_id)
```

Register it in `src/recruiter/main.py`: add `interviewers` to the import on line 11 and `_api_router.include_router(interviewers.router)` right after `interview.router`.

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/api/test_interviewers_api.py -q`
Expected: 7 passed

- [ ] **Step 6: Run the viewer matrix to confirm nothing opened by accident**

Run: `uv run pytest tests/api/test_viewer_matrix.py -q`
Expected: pass (PUT interviewers is refused to viewers by the app-wide guard; `require_role` only adds the recruiter/admin split)

- [ ] **Step 7: Commit**

```bash
git add src/recruiter/api/interviewers.py src/recruiter/api/users.py src/recruiter/schemas/user.py src/recruiter/main.py tests/api/test_interviewers_api.py
git commit -m "feat(interview-kit): assign interviewers to an application"
```

---

### Task 4: Sheet read, save, submit; stage rule; legacy submit route removed

**Files:**
- Modify: `src/recruiter/api/interview.py`
- Modify: `src/recruiter/api/applications.py:354-355` (set `closed_at` on manual move)
- Modify: `tests/api/test_interview_submit.py` (re-point to the sheet route)
- Modify: `tests/api/test_interview_api.py:129-157` (`test_patch_stores_answers_and_ratings` → answers live on sheets)
- Test: `tests/api/test_interview_sheets_api.py`

**Interfaces:**
- Produces: `GET /api/applications/{id}/interview-kit -> {kit, sheets: list[SheetRead]}` (sheets filtered by `visible_sheets`).
- Produces: `PATCH /api/applications/{id}/interview-kit/sheet` body `InterviewSheet` → `{kit, sheets}`; `POST …/interview-kit/sheet/submit` → `{kit, sheets}`.
- Removes: `POST /api/applications/{id}/interview-kit/submit`.
- Produces: helper `_own_assignment(session, app_row, user, *, create_for_recruiter: bool) -> InterviewAssignment` raising 404 when unassigned.

- [ ] **Step 1: Write the failing tests**

`tests/api/test_interview_sheets_api.py`:

```python
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recruiter.api.candidates import get_engine_dep, get_llm
from recruiter.auth.passwords import hash_password
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.models import Application, Candidate, InterviewAssignment, Job, Role, Stage, User
from recruiter.schemas.interview import GeneratedQuestion, GeneratedQuestions

PW = "pw-12345678"


async def _add(session: AsyncSession, email: str, role: Role) -> User:
    user = User(email=email, role=role, is_active=True, password_hash=hash_password(PW))
    session.add(user)
    await session.commit()
    return user


async def _login(client: AsyncClient, email: str) -> None:
    await client.post("/api/auth/logout")
    r = await client.post("/api/auth/login/password", json={"email": email, "password": PW})
    assert r.status_code == 204


async def _seed_scheduled_with_kit(session: AsyncSession) -> int:
    job = Job(title="Backend", description="x", criteria=[])
    session.add(job)
    await session.flush()
    cand = Candidate(source_type="paste", full_name="Marie", email="m@example.com")
    session.add(cand)
    await session.flush()
    app_row = Application(
        job_id=job.id, candidate_id=cand.id, stage=Stage.SCHEDULED, score=80,
        interview_kit={"status": "ready", "generated_at": "2026-09-14T00:00:00+00:00",
                       "questions": [{"id": "q1", "text": "Why?", "source": "probe"},
                                     {"id": "q2", "text": "How?", "source": "probe"}]},
    )
    session.add(app_row)
    await session.commit()
    return app_row.id


async def _assign(session: AsyncSession, app_id: int, *user_ids: int) -> None:
    for uid in user_ids:
        session.add(InterviewAssignment(application_id=app_id, user_id=uid))
    await session.commit()


SHEET = {"answers": {"q1": {"answer": "Two years on EKS.", "rating": "strong"}},
         "verdict": {"decision": "hire", "note": "Strong."}}


@pytest.mark.asyncio
async def test_assigned_interviewer_saves_and_reads_back_own_sheet(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_id = await _seed_scheduled_with_kit(db_session_with_schema)
    a = await _add(db_session_with_schema, "a@acme.com", Role.VIEWER)
    await _assign(db_session_with_schema, app_id, a.id)
    await _login(api_client_unauth, "a@acme.com")

    r = await api_client_unauth.patch(f"/api/applications/{app_id}/interview-kit/sheet", json=SHEET)
    assert r.status_code == 200
    sheets = r.json()["sheets"]
    assert len(sheets) == 1
    assert sheets[0]["user_id"] == a.id
    assert sheets[0]["sheet"]["answers"]["q1"]["rating"] == "strong"
    assert sheets[0]["sheet"]["verdict"]["decision"] == "hire"
    assert sheets[0]["submitted_at"] is None


@pytest.mark.asyncio
async def test_unassigned_caller_gets_404_on_sheet_routes(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_id = await _seed_scheduled_with_kit(db_session_with_schema)
    await _add(db_session_with_schema, "v@acme.com", Role.VIEWER)
    await _login(api_client_unauth, "v@acme.com")
    assert (await api_client_unauth.patch(
        f"/api/applications/{app_id}/interview-kit/sheet", json=SHEET)).status_code == 404
    assert (await api_client_unauth.post(
        f"/api/applications/{app_id}/interview-kit/sheet/submit")).status_code == 404


@pytest.mark.asyncio
async def test_second_submit_is_409(api_client: AsyncClient, create_scored_app) -> None:
    app_id = await create_scored_app()
    async with async_sessionmaker(app.dependency_overrides[get_engine_dep](), expire_on_commit=False)() as s:
        row = await s.get(Application, app_id)
        row.interview_kit = {"status": "ready", "questions": [{"id": "q1", "text": "Why?", "source": "probe"}]}
        await s.commit()
    assert (await api_client.post(f"/api/applications/{app_id}/interview-kit/sheet/submit")).status_code == 200
    assert (await api_client.post(f"/api/applications/{app_id}/interview-kit/sheet/submit")).status_code == 409
    assert (await api_client.patch(f"/api/applications/{app_id}/interview-kit/sheet", json=SHEET)).status_code == 409


@pytest.mark.asyncio
async def test_recruiter_with_no_assignments_gets_a_sheet_on_first_save(
    api_client: AsyncClient, create_scored_app,
) -> None:
    app_id = await create_scored_app()
    async with async_sessionmaker(app.dependency_overrides[get_engine_dep](), expire_on_commit=False)() as s:
        row = await s.get(Application, app_id)
        row.interview_kit = {"status": "ready", "questions": [{"id": "q1", "text": "Why?", "source": "probe"}]}
        await s.commit()
    r = await api_client.patch(f"/api/applications/{app_id}/interview-kit/sheet", json=SHEET)
    assert r.status_code == 200
    assert len(r.json()["sheets"]) == 1
    assert len((await api_client.get(f"/api/applications/{app_id}/interviewers")).json()) == 1


@pytest.mark.asyncio
async def test_answers_for_unknown_questions_are_dropped_on_save(
    api_client: AsyncClient, create_scored_app,
) -> None:
    app_id = await create_scored_app()
    async with async_sessionmaker(app.dependency_overrides[get_engine_dep](), expire_on_commit=False)() as s:
        row = await s.get(Application, app_id)
        row.interview_kit = {"status": "ready", "questions": [{"id": "q1", "text": "Why?", "source": "probe"}]}
        await s.commit()
    body = {"answers": {"q1": {"answer": "a", "rating": None}, "zzz": {"answer": "b", "rating": None}},
            "verdict": {"decision": None, "note": None}}
    r = await api_client.patch(f"/api/applications/{app_id}/interview-kit/sheet", json=body)
    assert set(r.json()["sheets"][0]["sheet"]["answers"]) == {"q1"}


@pytest.mark.asyncio
async def test_visibility_blind_until_submitted(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_id = await _seed_scheduled_with_kit(db_session_with_schema)
    a = await _add(db_session_with_schema, "a@acme.com", Role.VIEWER)
    b = await _add(db_session_with_schema, "b@acme.com", Role.VIEWER)
    rec = await _add(db_session_with_schema, "rec@acme.com", Role.RECRUITER)
    await _add(db_session_with_schema, "other@acme.com", Role.VIEWER)
    await _assign(db_session_with_schema, app_id, a.id, b.id)
    kit = f"/api/applications/{app_id}/interview-kit"

    await _login(api_client_unauth, "b@acme.com")
    await api_client_unauth.post(f"{kit}/sheet/submit")

    await _login(api_client_unauth, "a@acme.com")
    assert [s["user_id"] for s in (await api_client_unauth.get(kit)).json()["sheets"]] == [a.id]
    await api_client_unauth.post(f"{kit}/sheet/submit")
    assert {s["user_id"] for s in (await api_client_unauth.get(kit)).json()["sheets"]} == {a.id, b.id}

    await _login(api_client_unauth, "rec@acme.com")
    assert len((await api_client_unauth.get(kit)).json()["sheets"]) == 2

    await _login(api_client_unauth, "other@acme.com")
    assert (await api_client_unauth.get(kit)).json()["sheets"] == []
    assert rec.id  # silence unused warning


@pytest.mark.asyncio
async def test_stage_moves_only_when_every_sheet_is_in(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_id = await _seed_scheduled_with_kit(db_session_with_schema)
    a = await _add(db_session_with_schema, "a@acme.com", Role.VIEWER)
    b = await _add(db_session_with_schema, "b@acme.com", Role.VIEWER)
    await _assign(db_session_with_schema, app_id, a.id, b.id)
    kit = f"/api/applications/{app_id}/interview-kit"

    await _login(api_client_unauth, "a@acme.com")
    assert (await api_client_unauth.post(f"{kit}/sheet/submit")).status_code == 200
    assert (await api_client_unauth.get(f"/api/applications/{app_id}")).json()["stage"] == "scheduled"

    await _login(api_client_unauth, "b@acme.com")
    r = await api_client_unauth.post(f"{kit}/sheet/submit")
    assert r.json()["kit"]["closed_at"] is not None
    app_json = (await api_client_unauth.get(f"/api/applications/{app_id}")).json()
    assert app_json["stage"] == "interviewed"
    assert app_json["interviewed_at"] is not None


@pytest.mark.asyncio
async def test_manual_move_sets_closed_at_and_late_submit_does_not_move_again(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_id = await _seed_scheduled_with_kit(db_session_with_schema)
    a = await _add(db_session_with_schema, "a@acme.com", Role.VIEWER)
    await _add(db_session_with_schema, "rec@acme.com", Role.RECRUITER)
    await _assign(db_session_with_schema, app_id, a.id)
    kit = f"/api/applications/{app_id}/interview-kit"

    await _login(api_client_unauth, "rec@acme.com")
    r = await api_client_unauth.patch(f"/api/applications/{app_id}", json={"stage": "interviewed"})
    assert r.status_code == 200
    assert (await api_client_unauth.get(kit)).json()["kit"]["closed_at"] is not None
    # Recruiter moves it on to OFFER; the late sheet must not drag it back or forward.
    await api_client_unauth.patch(f"/api/applications/{app_id}", json={"stage": "offer"})

    await _login(api_client_unauth, "a@acme.com")
    assert (await api_client_unauth.patch(f"{kit}/sheet", json=SHEET)).status_code == 200
    assert (await api_client_unauth.post(f"{kit}/sheet/submit")).status_code == 200
    assert (await api_client_unauth.get(f"/api/applications/{app_id}")).json()["stage"] == "offer"


@pytest.mark.asyncio
async def test_sheet_routes_404_without_a_kit(api_client: AsyncClient, create_scored_app) -> None:
    app_id = await create_scored_app()
    assert (await api_client.patch(f"/api/applications/{app_id}/interview-kit/sheet", json=SHEET)).status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/api/test_interview_sheets_api.py -q`
Expected: FAIL — 404/405 on the sheet routes; `sheets` key missing on GET

- [ ] **Step 3: Implement in `src/recruiter/api/interview.py`**

Replace the imports block's model/schema lines and add the new ones:

```python
from recruiter.api.candidates import get_engine_dep, get_event_bus, get_llm
from recruiter.api.deps import get_session, require_user
from recruiter.api.interviewers import load_assignments
from recruiter.api.jobs import get_llm_or_none
from recruiter.events import EventBus
from recruiter.llm.client import LLMClient
from recruiter.models import Application, Candidate, InterviewAssignment, Job, Stage, User
from recruiter.pipeline.interview_kit import build_kit, merge_regenerated
from recruiter.pipeline.interview_kit_generator import draft_question, generate_probes
from recruiter.pipeline.interview_sheets import (
    all_submitted, can_edit_questions, prune_answers, visible_sheets,
)
from recruiter.schemas.interview import (
    BaselineQuestion,
    GeneratedQuestion,
    InterviewKit,
    InterviewSheet,
    KitQuestion,
    SheetRead,
)
from recruiter.schemas.job import CriteriaItem
from sqlalchemy import select
```

Replace `InterviewKitRead` and `get_kit`:

```python
class InterviewKitRead(BaseModel):
    kit: InterviewKit | None
    # Filtered per caller — see pipeline/interview_sheets.visible_sheets.
    sheets: list[SheetRead] = Field(default_factory=list)


async def _sheets_for(
    session: AsyncSession, app_row: Application, user: User,
) -> list[SheetRead]:
    rows = visible_sheets(await load_assignments(session, app_row.id), user=user)
    if not rows:
        return []
    users = {u.id: u for u in (await session.execute(
        select(User).where(User.id.in_([r.user_id for r in rows]))
    )).scalars().all()}
    return [
        SheetRead(
            user_id=r.user_id, name=users[r.user_id].name, email=users[r.user_id].email,
            sheet=InterviewSheet.model_validate(r.sheet or {}),
            submitted_at=r.submitted_at.isoformat() if r.submitted_at else None,
        )
        for r in rows
    ]


async def _read(session: AsyncSession, app_row: Application, user: User) -> InterviewKitRead:
    raw = app_row.interview_kit
    return InterviewKitRead(
        kit=InterviewKit.model_validate(raw) if raw else None,
        sheets=await _sheets_for(session, app_row, user),
    )


@router.get("/applications/{application_id}/interview-kit", response_model=InterviewKitRead)
async def get_kit(
    application_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> InterviewKitRead:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    return await _read(session, app_row, user)
```

Replace the whole `submit_kit` route with the sheet routes:

```python
async def _own_assignment(
    session: AsyncSession, app_row: Application, user: User,
) -> InterviewAssignment:
    """The caller's row, or 404. A recruiter/admin with no panel at all gets
    one created on the spot — that is what keeps the single-recruiter flow
    working with zero setup."""
    rows = await load_assignments(session, app_row.id)
    own = next((r for r in rows if r.user_id == user.id), None)
    if own is not None:
        return own
    if not rows and can_edit_questions(user):
        own = InterviewAssignment(application_id=app_row.id, user_id=user.id)
        session.add(own)
        await session.flush()
        return own
    raise HTTPException(status_code=404, detail="you are not assigned to this interview")


def _require_kit(app_row: Application) -> InterviewKit:
    if not app_row.interview_kit:
        raise HTTPException(status_code=404, detail="no interview kit; generate one first")
    return InterviewKit.model_validate(app_row.interview_kit)


@router.patch("/applications/{application_id}/interview-kit/sheet",
              response_model=InterviewKitRead)
async def patch_sheet(
    application_id: int,
    payload: InterviewSheet,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> InterviewKitRead:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    kit = _require_kit(app_row)
    own = await _own_assignment(session, app_row, user)
    if own.submitted_at is not None:
        raise HTTPException(status_code=409, detail="sheet already submitted")
    own.sheet = prune_answers(payload, {q.id for q in kit.questions}).model_dump()
    await session.commit()
    return await _read(session, app_row, user)


@router.post("/applications/{application_id}/interview-kit/sheet/submit",
             response_model=InterviewKitRead)
async def submit_sheet(
    application_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
    bus: EventBus = Depends(get_event_bus),
) -> InterviewKitRead:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    kit = _require_kit(app_row)
    own = await _own_assignment(session, app_row, user)
    if own.submitted_at is not None:
        raise HTTPException(status_code=409, detail="sheet already submitted")
    own.submitted_at = datetime.now(UTC)
    await session.flush()

    # Advance only from SCHEDULED, and only once every sheet is in. Already
    # interviewed or beyond means this is a late sheet on a closed round.
    if app_row.stage == Stage.SCHEDULED and all_submitted(await load_assignments(session, app_row.id)):
        app_row.stage = Stage.INTERVIEWED
        app_row.interviewed_at = datetime.now(UTC)
        kit.closed_at = _now()
        app_row.interview_kit = kit.model_dump()
    await session.commit()
    await bus.publish({
        "type": "interview_kit", "application_id": application_id, "status": kit.status,
    })
    return await _read(session, app_row, user)
```

In `src/recruiter/api/applications.py`, inside `patch_application`, change the `INTERVIEWED` branch:

```python
        elif new_stage == Stage.INTERVIEWED:
            app_row.interviewed_at = now
            # The recruiter closed the round by hand (a no-show, say). Stamp
            # the kit so late sheets know the round is over.
            if app_row.interview_kit:
                app_row.interview_kit = {**app_row.interview_kit, "closed_at": now.isoformat()}
```

- [ ] **Step 4: Re-point the legacy submit tests**

In `tests/api/test_interview_submit.py`, change every `f"/api/applications/{app_id}/interview-kit/submit"` to `f"/api/applications/{app_id}/interview-kit/sheet/submit"`, and in `test_submit_advances_scheduled_to_interviewed` replace

```python
    assert resp.json()["kit"]["submitted_at"] is not None
```

with

```python
    assert resp.json()["kit"]["closed_at"] is not None
    assert resp.json()["sheets"][0]["submitted_at"] is not None
```

In `test_submitting_again_does_not_advance_further` the second submit now returns 409 (sheet already submitted) — assert that status instead of 200, and keep the stage assertion. `test_submit_with_unanswered_questions_is_allowed` needs no change beyond the path.

In `tests/api/test_interview_api.py`, rename `test_patch_stores_answers_and_ratings` to `test_patch_keeps_questions_but_ignores_legacy_answer_fields` and assert that after PATCHing a question carrying `"answer": "A", "rating": "strong"`, the returned question has `answer is None` and `rating is None` (legacy fields are never written), while `text` round-trips.

- [ ] **Step 5: Make `patch_kit` ignore legacy fields**

In `patch_kit`, replace `kit.questions = payload.questions` with:

```python
    # Legacy per-question answer/rating are read-only: carry over whatever
    # the stored kit has and never take them from the client.
    legacy = {q.id: q for q in kit.questions}
    kit.questions = [
        q.model_copy(update={
            "answer": legacy[q.id].answer if q.id in legacy else None,
            "rating": legacy[q.id].rating if q.id in legacy else None,
        })
        for q in payload.questions
    ]
```

- [ ] **Step 6: Run the interview test files**

Run: `uv run pytest tests/api/test_interview_sheets_api.py tests/api/test_interview_submit.py tests/api/test_interview_api.py tests/api/test_interview_stage_wiring.py -q`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add src/recruiter/api/interview.py src/recruiter/api/applications.py tests/api/test_interview_sheets_api.py tests/api/test_interview_submit.py tests/api/test_interview_api.py
git commit -m "feat(interview-kit): per-interviewer sheets with blind visibility and all-in stage rule"
```

---

### Task 5: Question freeze and interviewer append-only edits

**Files:**
- Modify: `src/recruiter/api/interview.py` (`patch_kit`, `generate_kit`)
- Test: `tests/api/test_interview_freeze_api.py`

**Interfaces:**
- `PATCH /interview-kit`: 409 `"questions are frozen: a sheet has been submitted"` when a stored id is missing from the payload and any sheet is submitted; for a non-recruiter caller: 403 unless the payload equals the stored list plus appended questions; appended questions get `added_by = user.id`.
- `POST /interview-kit/generate`: 409 once frozen.

- [ ] **Step 1: Write the failing tests**

`tests/api/test_interview_freeze_api.py`:

```python
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.candidates import get_llm
from recruiter.auth.passwords import hash_password
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.models import Application, Candidate, InterviewAssignment, Job, Role, Stage, User

PW = "pw-12345678"
Q1 = {"id": "q1", "text": "Why?", "source": "probe"}
Q2 = {"id": "q2", "text": "How?", "source": "probe"}


async def _add(session: AsyncSession, email: str, role: Role) -> User:
    user = User(email=email, role=role, is_active=True, password_hash=hash_password(PW))
    session.add(user)
    await session.commit()
    return user


async def _login(client: AsyncClient, email: str) -> None:
    await client.post("/api/auth/logout")
    r = await client.post("/api/auth/login/password", json={"email": email, "password": PW})
    assert r.status_code == 204


async def _seed(session: AsyncSession) -> int:
    job = Job(title="Backend", description="x", criteria=[])
    session.add(job)
    await session.flush()
    cand = Candidate(source_type="paste", full_name="Marie", email="m@example.com")
    session.add(cand)
    await session.flush()
    app_row = Application(job_id=job.id, candidate_id=cand.id, stage=Stage.SCHEDULED, score=80,
                          interview_kit={"status": "ready", "questions": [Q1, Q2]})
    session.add(app_row)
    await session.commit()
    return app_row.id


@pytest.mark.asyncio
async def test_removal_and_regenerate_are_refused_after_first_submit(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_id = await _seed(db_session_with_schema)
    a = await _add(db_session_with_schema, "a@acme.com", Role.VIEWER)
    await _add(db_session_with_schema, "rec@acme.com", Role.RECRUITER)
    db_session_with_schema.add(InterviewAssignment(application_id=app_id, user_id=a.id))
    await db_session_with_schema.commit()
    kit = f"/api/applications/{app_id}/interview-kit"

    await _login(api_client_unauth, "a@acme.com")
    assert (await api_client_unauth.post(f"{kit}/sheet/submit")).status_code == 200

    await _login(api_client_unauth, "rec@acme.com")
    r = await api_client_unauth.patch(kit, json={"questions": [Q1]})
    assert r.status_code == 409
    # Renaming keeps ids, so it is still allowed.
    r = await api_client_unauth.patch(kit, json={"questions": [{**Q1, "text": "Why us?"}, Q2]})
    assert r.status_code == 200
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()
    try:
        assert (await api_client_unauth.post(f"{kit}/generate")).status_code == 409
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_assigned_interviewer_may_only_append(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_id = await _seed(db_session_with_schema)
    a = await _add(db_session_with_schema, "a@acme.com", Role.VIEWER)
    db_session_with_schema.add(InterviewAssignment(application_id=app_id, user_id=a.id))
    await db_session_with_schema.commit()
    kit = f"/api/applications/{app_id}/interview-kit"
    await _login(api_client_unauth, "a@acme.com")

    new_q = {"id": "mine", "text": "On-call?", "source": "probe"}
    r = await api_client_unauth.patch(kit, json={"questions": [Q1, Q2, new_q]})
    assert r.status_code == 200
    added = [q for q in r.json()["kit"]["questions"] if q["id"] == "mine"][0]
    assert added["added_by"] == a.id
    assert [q["added_by"] for q in r.json()["kit"]["questions"][:2]] == [None, None]

    assert (await api_client_unauth.patch(kit, json={"questions": [Q2, Q1, new_q]})).status_code == 403
    assert (await api_client_unauth.patch(kit, json={"questions": [{**Q1, "text": "x"}, Q2, new_q]})).status_code == 403
    assert (await api_client_unauth.patch(kit, json={"questions": [Q1, new_q]})).status_code == 403


@pytest.mark.asyncio
async def test_unassigned_viewer_cannot_touch_questions(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    app_id = await _seed(db_session_with_schema)
    await _add(db_session_with_schema, "v@acme.com", Role.VIEWER)
    await _login(api_client_unauth, "v@acme.com")
    r = await api_client_unauth.patch(f"/api/applications/{app_id}/interview-kit",
                                      json={"questions": [Q1, Q2, {"id": "x", "text": "?", "source": "probe"}]})
    assert r.status_code == 403
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/api/test_interview_freeze_api.py -q`
Expected: FAIL — first test gets 200 where 409 expected; second gets 403 on the append (viewer guard, route not yet allow-listed) — that 403 is fixed in Task 6; for now assert the freeze test alone fails as described.

- [ ] **Step 3: Implement**

In `patch_kit`, add `user: User = Depends(require_user)` to the signature and replace the body after the duplicate-id check with:

```python
    kit = InterviewKit.model_validate(app_row.interview_kit)
    rows = await load_assignments(session, application_id)
    stored_ids = [q.id for q in kit.questions]
    incoming_ids = [q.id for q in payload.questions]

    if not can_edit_questions(user):
        # An assigned interviewer may append, and nothing else.
        if user.id not in {r.user_id for r in rows}:
            raise HTTPException(status_code=403, detail="not assigned to this interview")
        prefix = payload.questions[:len(stored_ids)]
        unchanged = [q.model_dump(exclude={"added_by", "answer", "rating"}) for q in prefix] == [
            q.model_dump(exclude={"added_by", "answer", "rating"}) for q in kit.questions
        ]
        if not unchanged:
            raise HTTPException(status_code=403, detail="interviewers may only add questions")

    if is_frozen(rows) and any(qid not in incoming_ids for qid in stored_ids):
        raise HTTPException(
            status_code=409, detail="questions are frozen: a sheet has been submitted",
        )

    # Legacy per-question answer/rating are read-only: carry over whatever
    # the stored kit has and never take them from the client. `added_by`
    # is server-assigned on append and preserved otherwise.
    legacy = {q.id: q for q in kit.questions}
    kit.questions = [
        q.model_copy(update={
            "answer": legacy[q.id].answer if q.id in legacy else None,
            "rating": legacy[q.id].rating if q.id in legacy else None,
            "added_by": legacy[q.id].added_by if q.id in legacy
                        else (None if can_edit_questions(user) else user.id),
        })
        for q in payload.questions
    ]
    app_row.interview_kit = kit.model_dump()
    await session.commit()
    return await _read(session, app_row, user)
```

(Add `is_frozen` to the `interview_sheets` import.)

In `generate_kit`, after the 404 check:

```python
    if is_frozen(await load_assignments(session, application_id)):
        raise HTTPException(
            status_code=409, detail="questions are frozen: a sheet has been submitted",
        )
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/api/test_interview_freeze_api.py -q`
Expected: first test passes; the two append tests still fail with 403 from the app-wide viewer guard (fixed next task).

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/api/interview.py tests/api/test_interview_freeze_api.py
git commit -m "feat(interview-kit): freeze questions after first submit; interviewers append only"
```

---

### Task 6: Viewer exception

**Files:**
- Modify: `src/recruiter/api/permissions.py`
- Test: `tests/api/test_interview_freeze_api.py` (now green), `tests/api/test_viewer_interviewer_exception.py`

- [ ] **Step 1: Write the failing test**

`tests/api/test_viewer_interviewer_exception.py`:

```python
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.auth.passwords import hash_password
from recruiter.models import Application, Candidate, InterviewAssignment, Job, Role, Stage, User

PW = "pw-12345678"
SHEET = {"answers": {}, "verdict": {"decision": "unsure", "note": None}}


async def _add(session: AsyncSession, email: str, role: Role) -> User:
    user = User(email=email, role=role, is_active=True, password_hash=hash_password(PW))
    session.add(user)
    await session.commit()
    return user


async def _login(client: AsyncClient, email: str) -> None:
    await client.post("/api/auth/logout")
    r = await client.post("/api/auth/login/password", json={"email": email, "password": PW})
    assert r.status_code == 204


async def _seed(session: AsyncSession) -> int:
    job = Job(title="Backend", description="x", criteria=[])
    session.add(job)
    await session.flush()
    cand = Candidate(source_type="paste", full_name="Marie", email="m@example.com")
    session.add(cand)
    await session.flush()
    app_row = Application(job_id=job.id, candidate_id=cand.id, stage=Stage.SCHEDULED, score=80,
                          interview_kit={"status": "ready",
                                         "questions": [{"id": "q1", "text": "Why?", "source": "probe"}]})
    session.add(app_row)
    await session.commit()
    return app_row.id


@pytest.mark.asyncio
async def test_assigned_viewer_writes_only_their_own_sheet(
    api_client_unauth: AsyncClient, db_session_with_schema: AsyncSession,
) -> None:
    assigned_app = await _seed(db_session_with_schema)
    other_app = await _seed(db_session_with_schema)
    v = await _add(db_session_with_schema, "v@acme.com", Role.VIEWER)
    db_session_with_schema.add(InterviewAssignment(application_id=assigned_app, user_id=v.id))
    await db_session_with_schema.commit()
    await _login(api_client_unauth, "v@acme.com")

    ok = await api_client_unauth.patch(f"/api/applications/{assigned_app}/interview-kit/sheet", json=SHEET)
    assert ok.status_code == 200

    # Not assigned there: the handler's row check, not the guard, says no.
    assert (await api_client_unauth.patch(
        f"/api/applications/{other_app}/interview-kit/sheet", json=SHEET)).status_code == 404

    # Everything else a viewer could not do before, they still cannot.
    assert (await api_client_unauth.patch(
        f"/api/applications/{assigned_app}", json={"stage": "interviewed"})).status_code == 403
    assert (await api_client_unauth.post(
        f"/api/applications/{assigned_app}/interview-kit/generate")).status_code == 403
    assert (await api_client_unauth.put(
        f"/api/applications/{assigned_app}/interviewers", json={"user_ids": []})).status_code == 403
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/api/test_viewer_interviewer_exception.py -q`
Expected: FAIL — the sheet PATCH returns 403 (read-only role)

- [ ] **Step 3: Allow-list the routes**

In `src/recruiter/api/permissions.py`, add to `VIEWER_ALLOWED_ROUTES`:

```python
    # Interviewer sheets. A viewer assigned to a candidate may write exactly
    # one thing: their own sheet on that candidate. The allow list is per
    # route, so it cannot express "own sheet only" — each handler in
    # api/interview.py checks the assignment row itself (404 when
    # unassigned, 409 when submitted). Allow-listing these WITHOUT that row
    # check would let any viewer write feedback on any candidate. The kit
    # PATCH is here because an interviewer may APPEND a question; the
    # handler refuses every other change from a non-recruiter with 403.
    ("PATCH", "/api/applications/{application_id}/interview-kit/sheet"),
    ("POST", "/api/applications/{application_id}/interview-kit/sheet/submit"),
    ("PATCH", "/api/applications/{application_id}/interview-kit"),
```

And extend the module docstring with one paragraph:

```
The interviewer-sheet routes are the second deliberate exception (chat was
the first): a viewer can be an interviewer, and an interviewer must write
their own feedback. See docs/superpowers/specs/2026-09-14-multi-interviewer-design.md.
```

- [ ] **Step 4: Run the exception, freeze, and matrix tests**

Run: `uv run pytest tests/api/test_viewer_interviewer_exception.py tests/api/test_interview_freeze_api.py tests/api/test_viewer_matrix.py -q`
Expected: all pass. If `test_viewer_matrix.py` enumerates every allow-listed route, add the three new entries to its expectation with the same comment.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/api/permissions.py tests/api/test_viewer_interviewer_exception.py tests/api/test_viewer_matrix.py
git commit -m "sec(permissions): let an assigned viewer write their own interview sheet"
```

---

### Task 7: Sheet counts on application reads

**Files:**
- Modify: `src/recruiter/schemas/application.py` (`ApplicationRead`)
- Modify: `src/recruiter/api/applications.py` (`_to_read`, `get_application`, `list_applications_for_job`, `patch_application` return)
- Test: `tests/api/test_application_sheet_counts.py`

**Interfaces:**
- Produces: `ApplicationRead.sheets_total: int = 0`, `ApplicationRead.sheets_submitted: int = 0`.
- Produces: `_sheet_counts(session, application_ids) -> dict[int, tuple[int, int]]`.

- [ ] **Step 1: Write the failing test**

```python
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
    async with async_sessionmaker(app.dependency_overrides[get_engine_dep](), expire_on_commit=False)() as s:
        a = User(email="a@acme.com", role=Role.VIEWER, is_active=True)
        b = User(email="b@acme.com", role=Role.VIEWER, is_active=True)
        s.add_all([a, b])
        await s.flush()
        s.add_all([
            InterviewAssignment(application_id=app_id, user_id=a.id, submitted_at=datetime.now(UTC)),
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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/api/test_application_sheet_counts.py -q`
Expected: FAIL with `KeyError: 'sheets_total'`

- [ ] **Step 3: Implement**

Schema: add to `ApplicationRead`:

```python
    # Interviewer sheets on this application; the kanban shows "n/m sheets
    # in" while SCHEDULED. Batched in one query per read — see _sheet_counts.
    sheets_total: int = 0
    sheets_submitted: int = 0
```

In `applications.py`, import `InterviewAssignment` and add next to `_latest_errors`:

```python
async def _sheet_counts(
    session: AsyncSession, application_ids: list[int]
) -> dict[int, tuple[int, int]]:
    """application id → (assigned, submitted). One query for the board."""
    if not application_ids:
        return {}
    rows = (await session.execute(
        select(
            InterviewAssignment.application_id,
            func.count(InterviewAssignment.id),
            func.count(InterviewAssignment.submitted_at),
        )
        .where(InterviewAssignment.application_id.in_(application_ids))
        .group_by(InterviewAssignment.application_id)
    )).all()
    return {app_id: (total, submitted) for app_id, total, submitted in rows}
```

Change `_to_read` to take a third optional argument and pass it through:

```python
def _to_read(
    app_row: Application,
    last_error: tuple[str, int] | None = None,
    sheet_counts: tuple[int, int] = (0, 0),
) -> ApplicationRead:
    ...
        enrichment=app_row.enrichment,
        sheets_total=sheet_counts[0],
        sheets_submitted=sheet_counts[1],
    )
```

Update the three call sites:

```python
# get_application
    errors = await _latest_errors(session, [app_row.id])
    counts = await _sheet_counts(session, [app_row.id])
    return _to_read(app_row, errors.get(app_row.id), counts.get(app_row.id, (0, 0)))

# list_applications_for_job
    errors = await _latest_errors(session, [r.id for r in rows])
    counts = await _sheet_counts(session, [r.id for r in rows])
    return [_to_read(r, errors.get(r.id), counts.get(r.id, (0, 0))) for r in rows]

# patch_application (last line)
    counts = await _sheet_counts(session, [app_row.id])
    return _to_read(app_row, sheet_counts=counts.get(app_row.id, (0, 0)))
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/api/test_application_sheet_counts.py tests/api/test_applications_api.py -q`
Expected: pass (use the actual applications test file name in `tests/api`)

- [ ] **Step 5: Run the whole backend suite, then commit**

Run: `uv run pytest -q`
Expected: all pass

```bash
git add src/recruiter/schemas/application.py src/recruiter/api/applications.py tests/api/test_application_sheet_counts.py
git commit -m "feat(interview-kit): sheet counts on application reads"
```

---

### Task 8: Frontend hooks and types

**Files:**
- Modify: `recruiter-frontend/src/hooks/use-interview-kit.ts`
- Create: `recruiter-frontend/src/hooks/use-interviewers.ts`
- Modify: `recruiter-frontend/src/lib/query-keys.ts`, `recruiter-frontend/src/lib/sse.ts`
- Modify: `recruiter-frontend/src/hooks/use-job-applications.ts` (`sheets_total?`, `sheets_submitted?`)
- Test: `recruiter-frontend/src/hooks/use-interview-kit.test.tsx`, `recruiter-frontend/src/lib/sse.test.ts` (extend if present, else create)

**Interfaces:**
- Produces from `use-interview-kit.ts`:
  ```ts
  export type VerdictDecision = "hire" | "no_hire" | "unsure";
  export interface SheetAnswer { answer: string | null; rating: Rating | null }
  export interface InterviewSheet { answers: Record<string, SheetAnswer>; verdict: { decision: VerdictDecision | null; note: string | null } }
  export interface SheetRead { user_id: number; name: string | null; email: string; sheet: InterviewSheet; submitted_at: string | null }
  export const EMPTY_SHEET: InterviewSheet;
  // KitQuestion gains added_by?: number | null; InterviewKit gains closed_at?: string | null
  // useInterviewKit(...) returns additionally: sheets: SheetRead[], saveSheet: UseMutationResult<..., InterviewSheet>, submitSheet: UseMutationResult<...>
  // `submit` and `patch` (questions) remain; `submit` now calls /interview-kit/sheet/submit
  ```
- Produces from `use-interviewers.ts`: `useInterviewers(applicationId)` → `{ interviewers: InterviewerRead[], isLoading, setInterviewers: UseMutationResult<..., number[]> }`; `useUserDirectory(enabled: boolean)` → query of `DirectoryUser[]`.
- Produces in `query-keys.ts`: `interviewers: (applicationId) => ["interviewers", applicationId]`, `userDirectory: () => ["users", "directory"]`.

- [ ] **Step 1: Write the failing hook test**

`src/hooks/use-interview-kit.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { EMPTY_SHEET, useInterviewKit } from "./use-interview-kit";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const KIT = { status: "ready", questions: [{ id: "q1", text: "Why?", source: "probe", answer: null, rating: null }] };

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("useInterviewKit sheets", () => {
  it("exposes the caller-visible sheets and saves through the sheet route", async () => {
    const seen: { body?: unknown; path?: string } = {};
    server.use(
      http.get("http://localhost:8000/api/applications/1/interview-kit", () =>
        HttpResponse.json({ kit: KIT, sheets: [{ user_id: 4, name: "Ann", email: "ann@acme.com", sheet: EMPTY_SHEET, submitted_at: null }] })),
      http.patch("http://localhost:8000/api/applications/1/interview-kit/sheet", async ({ request }) => {
        seen.body = await request.json();
        seen.path = new URL(request.url).pathname;
        return HttpResponse.json({ kit: KIT, sheets: [] });
      }),
    );
    const { result } = renderHook(() => useInterviewKit(1), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.sheets).toHaveLength(1));
    expect(result.current.sheets[0].name).toBe("Ann");

    result.current.saveSheet.mutate({ ...EMPTY_SHEET, verdict: { decision: "hire", note: null } });
    await waitFor(() => expect(seen.path).toBe("/api/applications/1/interview-kit/sheet"));
    expect((seen.body as { verdict: { decision: string } }).verdict.decision).toBe("hire");
  });

  it("submits through the sheet submit route", async () => {
    let hit = "";
    server.use(
      http.get("http://localhost:8000/api/applications/1/interview-kit", () =>
        HttpResponse.json({ kit: KIT, sheets: [] })),
      http.post("http://localhost:8000/api/applications/1/interview-kit/sheet/submit", ({ request }) => {
        hit = new URL(request.url).pathname;
        return HttpResponse.json({ kit: KIT, sheets: [] });
      }),
    );
    const { result } = renderHook(() => useInterviewKit(1), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.kit).not.toBeNull());
    result.current.submitSheet.mutate();
    await waitFor(() => expect(hit).toBe("/api/applications/1/interview-kit/sheet/submit"));
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd recruiter-frontend && npx vitest --run src/hooks/use-interview-kit.test.tsx`
Expected: FAIL — `EMPTY_SHEET` is not exported; `sheets` undefined

- [ ] **Step 3: Implement the hook changes**

`src/lib/query-keys.ts`: add

```ts
  interviewers: (applicationId: number) => ["interviewers", applicationId] as const,
  userDirectory: () => ["users", "directory"] as const,
```

`src/hooks/use-interview-kit.ts`: add the types and `EMPTY_SHEET`, change the response type, add the mutations, and re-point `submit`:

```ts
export type VerdictDecision = "hire" | "no_hire" | "unsure";

export interface SheetAnswer {
  answer: string | null;
  rating: Rating | null;
}

export interface InterviewSheet {
  answers: Record<string, SheetAnswer>;
  verdict: { decision: VerdictDecision | null; note: string | null };
}

export interface SheetRead {
  user_id: number;
  name: string | null;
  email: string;
  sheet: InterviewSheet;
  submitted_at: string | null;
}

export const EMPTY_SHEET: InterviewSheet = {
  answers: {},
  verdict: { decision: null, note: null },
};

export interface KitQuestion {
  id: string;
  text: string;
  source: "baseline" | "probe";
  criterion?: string | null;
  /** Legacy — answers now live on each interviewer's sheet. Read-only. */
  answer: string | null;
  rating: Rating | null;
  added_by?: number | null;
}

export interface InterviewKit {
  status: "generating" | "ready" | "error";
  error?: string | null;
  generated_at?: string | null;
  submitted_at?: string | null;
  closed_at?: string | null;
  questions: KitQuestion[];
}

interface KitResponse {
  kit: InterviewKit | null;
  sheets: SheetRead[];
}
```

Inside `useInterviewKit`:

```ts
  const query = useQuery({
    queryKey: key,
    queryFn: () => api<KitResponse>(path),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: key });
    qc.invalidateQueries({ queryKey: queryKeys.interviewers(applicationId) });
  };

  const saveSheet = useMutation({
    mutationFn: (sheet: InterviewSheet) =>
      api<KitResponse>(`${path}/sheet`, { method: "PATCH", json: sheet }),
    onSuccess: invalidate,
  });

  const submitSheet = useMutation({
    mutationFn: () => api<KitResponse>(`${path}/sheet/submit`, { method: "POST" }),
    onSuccess: () => {
      invalidate();
      // The stage may have changed, so the kanban and the detail header are stale too.
      qc.invalidateQueries({ queryKey: queryKeys.application(applicationId) });
      qc.invalidateQueries({ queryKey: ["jobs"], exact: false });
    },
  });
```

Return `sheets: query.data?.sheets ?? []`, `saveSheet`, `submitSheet`; delete the old `submit` mutation (its only caller is rewritten in Task 10) and make `patch`'s `mutationFn` return `api<KitResponse>`.

`src/hooks/use-job-applications.ts`: add to `ApplicationRead`:

```ts
  /** Interviewer sheets assigned / submitted. Shown as "n/m sheets in" while scheduled. */
  sheets_total?: number;
  sheets_submitted?: number;
```

`src/lib/sse.ts`: in `handleServerEvent`'s `interview_kit` branch, also invalidate:

```ts
    queryClient.invalidateQueries({ queryKey: queryKeys.interviewers(payload.application_id) });
    // A sheet submit can move the stage.
    queryClient.invalidateQueries({ queryKey: queryKeys.application(payload.application_id) });
    queryClient.invalidateQueries({ queryKey: ["jobs"], exact: false });
```

- [ ] **Step 4: Write `use-interviewers.ts`**

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

export interface InterviewerRead {
  user_id: number;
  name: string | null;
  email: string;
  submitted_at: string | null;
}

export interface DirectoryUser {
  id: number;
  name: string | null;
  email: string;
  role: "admin" | "recruiter" | "viewer";
}

export function useInterviewers(applicationId: number) {
  const qc = useQueryClient();
  const key = queryKeys.interviewers(applicationId);
  const path = `/api/applications/${applicationId}/interviewers`;
  const query = useQuery({
    queryKey: key,
    queryFn: () => api<InterviewerRead[]>(path),
    enabled: !Number.isNaN(applicationId),
  });
  const setInterviewers = useMutation({
    mutationFn: (userIds: number[]) =>
      api<InterviewerRead[]>(path, { method: "PUT", json: { user_ids: userIds } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: queryKeys.interviewKit(applicationId) });
      qc.invalidateQueries({ queryKey: queryKeys.application(applicationId) });
    },
  });
  return { interviewers: query.data ?? [], isLoading: query.isLoading, setInterviewers };
}

/** Only fetched when the picker opens — a recruiter-only endpoint, and
 *  viewers never open the picker. */
export function useUserDirectory(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.userDirectory(),
    queryFn: () => api<DirectoryUser[]>("/api/users/directory"),
    enabled,
  });
}
```

- [ ] **Step 5: Run the hook test and TypeScript**

Run: `npx vitest --run src/hooks/use-interview-kit.test.tsx && npx tsc --noEmit`
Expected: test passes; `tsc` reports errors only in `interview-kit-section.tsx` (uses removed `submit`), fixed in Task 10. If `tsc` blocks CI, temporarily keep `submit` as an alias of `submitSheet` and remove it in Task 10.

- [ ] **Step 6: Commit**

```bash
git add src/hooks/use-interview-kit.ts src/hooks/use-interviewers.ts src/hooks/use-interview-kit.test.tsx src/lib/query-keys.ts src/lib/sse.ts src/hooks/use-job-applications.ts
git commit -m "feat(interview-kit): frontend hooks for interviewer sheets and assignments"
```

---

### Task 9: Interviewers picker

**Files:**
- Create: `recruiter-frontend/src/components/candidate/interviewers-picker.tsx`
- Modify: `recruiter-frontend/src/routes/application-detail.tsx:69-84` (render it on the stage line)
- Test: `recruiter-frontend/src/components/candidate/interviewers-picker.test.tsx`

**Interfaces:**
- Produces: `<InterviewersPicker applicationId={number} canWrite={boolean} />`. Renders chips `name ?? email` with a `✓` (`aria-label="submitted"`) when `submitted_at` is set; an "Assign" button (writers only) opens a `Dialog` with a search `Input` and a checkbox per active directory user; "Save" calls `setInterviewers` with the checked ids.

- [ ] **Step 1: Write the failing test**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { InterviewersPicker } from "./interviewers-picker";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function mount(canWrite: boolean, capture: { body?: any } = {}) {
  server.use(
    http.get("http://localhost:8000/api/applications/1/interviewers", () =>
      HttpResponse.json([{ user_id: 2, name: "Bob", email: "bob@acme.com", submitted_at: "2026-09-14T10:00:00Z" }])),
    http.get("http://localhost:8000/api/users/directory", () =>
      HttpResponse.json([
        { id: 2, name: "Bob", email: "bob@acme.com", role: "viewer" },
        { id: 3, name: null, email: "carol@acme.com", role: "recruiter" },
      ])),
    http.put("http://localhost:8000/api/applications/1/interviewers", async ({ request }) => {
      capture.body = await request.json();
      return HttpResponse.json([]);
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return render(<Wrapper><InterviewersPicker applicationId={1} canWrite={canWrite} /></Wrapper>);
}

describe("InterviewersPicker", () => {
  it("shows assigned interviewers with a submitted mark", async () => {
    mount(false);
    expect(await screen.findByText("Bob")).toBeInTheDocument();
    expect(screen.getByLabelText("submitted")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /assign/i })).not.toBeInTheDocument();
  });

  it("lets a writer reconcile the list", async () => {
    const capture: { body?: any } = {};
    mount(true, capture);
    await userEvent.click(await screen.findByRole("button", { name: /assign/i }));
    const carol = await screen.findByRole("checkbox", { name: /carol@acme.com/ });
    expect(screen.getByRole("checkbox", { name: /bob@acme.com/ })).toBeChecked();
    await userEvent.click(carol);
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(capture.body).toEqual({ user_ids: [2, 3] }));
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest --run src/components/candidate/interviewers-picker.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement**

`src/components/candidate/interviewers-picker.tsx`:

```tsx
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useInterviewers, useUserDirectory } from "@/hooks/use-interviewers";
import { ApiError } from "@/lib/api";

interface Props {
  applicationId: number;
  canWrite: boolean;
}

export function InterviewersPicker({ applicationId, canWrite }: Props) {
  const { interviewers, setInterviewers } = useInterviewers(applicationId);
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [checked, setChecked] = useState<number[]>([]);
  const directory = useUserDirectory(open);

  function openDialog() {
    setChecked(interviewers.map((i) => i.user_id));
    setFilter("");
    setOpen(true);
  }

  const visible = (directory.data ?? []).filter((u) => {
    const q = filter.trim().toLowerCase();
    return !q || u.email.toLowerCase().includes(q) || (u.name ?? "").toLowerCase().includes(q);
  });

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
        interviewers:
      </span>
      {interviewers.length === 0 && (
        <span className="text-sm text-muted-foreground">none</span>
      )}
      {interviewers.map((i) => (
        <span
          key={i.user_id}
          className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-xs"
        >
          {i.name ?? i.email}
          {i.submitted_at && <span aria-label="submitted" className="text-emerald-400">✓</span>}
        </span>
      ))}
      {canWrite && (
        <Button variant="outline" size="sm" className="h-auto px-2 py-1 text-xs" onClick={openDialog}>
          Assign
        </Button>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Assign interviewers</DialogTitle>
          </DialogHeader>
          <Input
            placeholder="Search by name or email"
            aria-label="Search users"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <ul className="max-h-72 space-y-1 overflow-y-auto">
            {visible.map((u) => {
              const label = u.name ? `${u.name} (${u.email})` : u.email;
              return (
                <li key={u.id}>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      aria-label={label}
                      checked={checked.includes(u.id)}
                      onChange={(e) =>
                        setChecked((ids) =>
                          e.target.checked ? [...ids, u.id] : ids.filter((x) => x !== u.id))}
                    />
                    {label}
                  </label>
                </li>
              );
            })}
          </ul>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button
              disabled={setInterviewers.isPending}
              onClick={() =>
                setInterviewers.mutate(checked, {
                  onSuccess: () => setOpen(false),
                  onError: (err) =>
                    toast.error(err instanceof ApiError ? err.detail : "Couldn't save interviewers"),
                })}
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
```

In `application-detail.tsx`, directly under the stage row `<div className="flex items-center gap-3 flex-wrap">…</div>`, add:

```tsx
        <InterviewersPicker applicationId={id} canWrite={canWrite} />
```

with the import `import { InterviewersPicker } from "@/components/candidate/interviewers-picker";`.

- [ ] **Step 4: Run**

Run: `npx vitest --run src/components/candidate/interviewers-picker.test.tsx && npx tsc --noEmit`
Expected: 2 passed; `tsc` clean except the known `interview-kit-section.tsx` error if the `submit` alias was not kept.

- [ ] **Step 5: Commit**

```bash
git add src/components/candidate/interviewers-picker.tsx src/components/candidate/interviewers-picker.test.tsx src/routes/application-detail.tsx
git commit -m "ui(interview-kit): assign interviewers from the candidate page"
```

---

### Task 10: Interview kit section on sheets, verdict, submit dialog, freeze, legacy answers

**Files:**
- Modify: `recruiter-frontend/src/components/candidate/interview-kit-section.tsx`
- Modify: `recruiter-frontend/src/components/candidate/interview-kit-section.test.tsx`

**Interfaces:**
- Consumes: `useInterviewKit` from Task 8 (`kit`, `sheets`, `saveSheet`, `submitSheet`, `patch`, `generate`, `draftQuestion`), `useCurrentUser` for the caller id.
- Props unchanged: `{ applicationId, canWrite }`. `canWrite` now means "may edit questions" (recruiter/admin). Whether the caller may write a sheet is derived: `mySheet = sheets.find(s => s.user_id === me.id)`; a writer with no sheets at all may also write (auto-create).
- Produces: a `ConfirmSubmitDialog` replacing `window.confirm`, rendered from a `Dialog`, with buttons "Submit anyway" / "Keep editing".

- [ ] **Step 1: Update the tests**

In `interview-kit-section.test.tsx`, change `mountWithKit` to accept `sheets` and a current-user handler, and replace the answer/rating/submit tests:

```tsx
function mountWithKit(
  kit: unknown,
  capture: { body?: any; sheet?: any; submitted?: boolean } = {},
  opts: { sheets?: unknown[]; me?: { id: number; role: string }; canWrite?: boolean } = {},
) {
  const me = opts.me ?? { id: 1, role: "recruiter" };
  server.use(
    http.get("http://localhost:8000/api/auth/me", () =>
      HttpResponse.json({ id: me.id, email: "me@acme.com", name: "Me", picture: null, role: me.role })),
    http.get("http://localhost:8000/api/applications/1/interview-kit", () =>
      HttpResponse.json({ kit, sheets: opts.sheets ?? [] })),
    http.patch("http://localhost:8000/api/applications/1/interview-kit", async ({ request }) => {
      capture.body = await request.json();
      return HttpResponse.json({ kit, sheets: opts.sheets ?? [] });
    }),
    http.patch("http://localhost:8000/api/applications/1/interview-kit/sheet", async ({ request }) => {
      capture.sheet = await request.json();
      return HttpResponse.json({ kit, sheets: opts.sheets ?? [] });
    }),
    http.post("http://localhost:8000/api/applications/1/interview-kit/sheet/submit", () => {
      capture.submitted = true;
      return HttpResponse.json({ kit, sheets: opts.sheets ?? [] });
    }),
    http.post("http://localhost:8000/api/applications/1/interview-kit/generate", () =>
      HttpResponse.json({ application_id: 1 }, { status: 202 })),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}<Toaster /></QueryClientProvider>
  );
  return render(<Wrapper><InterviewKitSection applicationId={1} canWrite={opts.canWrite ?? true} /></Wrapper>);
}
```

Then these tests (keep the existing question-editing tests; they still PATCH `/interview-kit`):

```tsx
  it("saves answers and ratings to the caller's sheet", async () => {
    const capture: { sheet?: any } = {};
    mountWithKit(READY, capture);
    await screen.findByDisplayValue("Why this role?");
    await userEvent.type(screen.getByPlaceholder(/what they said/i), "Good answer");
    await userEvent.click(screen.getByRole("button", { name: /rate question 1 as strong/i }));
    await userEvent.click(screen.getByRole("button", { name: /save answers/i }));
    await waitFor(() => expect(capture.sheet).toBeDefined());
    expect(capture.sheet.answers.b1).toEqual({ answer: "Good answer", rating: "strong" });
  });

  it("records a verdict on the sheet", async () => {
    const capture: { sheet?: any } = {};
    mountWithKit(READY, capture);
    await screen.findByDisplayValue("Why this role?");
    await userEvent.click(screen.getByRole("button", { name: /^hire$/i }));
    await userEvent.type(screen.getByLabelText(/verdict note/i), "Strong on infra.");
    await userEvent.click(screen.getByRole("button", { name: /save answers/i }));
    await waitFor(() => expect(capture.sheet?.verdict).toEqual({ decision: "hire", note: "Strong on infra." }));
  });

  it("asks before submitting with unanswered questions, then submits the sheet", async () => {
    const capture: { sheet?: any; submitted?: boolean } = {};
    mountWithKit(READY, capture);
    await screen.findByDisplayValue("Why this role?");
    await userEvent.click(screen.getByRole("button", { name: /submit interview/i }));
    expect(await screen.findByRole("dialog")).toHaveTextContent(/2 question\(s\) have no answer/);
    await userEvent.click(screen.getByRole("button", { name: /submit anyway/i }));
    await waitFor(() => expect(capture.submitted).toBe(true));
  });

  it("renders a submitted sheet read-only", async () => {
    const mine = { user_id: 1, name: "Me", email: "me@acme.com",
      sheet: { answers: { b1: { answer: "Done", rating: "weak" } }, verdict: { decision: "no_hire", note: null } },
      submitted_at: "2026-09-14T10:00:00Z" };
    mountWithKit(READY, {}, { sheets: [mine] });
    await screen.findByDisplayValue("Why this role?");
    expect(screen.queryByRole("button", { name: /submit interview/i })).not.toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();
  });

  it("disables removal and regenerate once any sheet is submitted", async () => {
    const other = { user_id: 7, name: "Bob", email: "bob@acme.com", sheet: { answers: {}, verdict: { decision: null, note: null } }, submitted_at: "2026-09-14T10:00:00Z" };
    mountWithKit(READY, {}, { sheets: [other] });
    await screen.findByDisplayValue("Why this role?");
    expect(screen.getByRole("button", { name: /remove question 1/i })).toBeDisabled();
  });

  it("shows legacy per-question answers read-only", async () => {
    const legacy = { ...READY, questions: [{ ...READY.questions[0], answer: "Old answer", rating: "strong" }] };
    mountWithKit(legacy);
    await screen.findByDisplayValue("Why this role?");
    expect(screen.getByText(/recorded before interviewer sheets/i)).toBeInTheDocument();
    expect(screen.getByText("Old answer")).toBeInTheDocument();
  });

  it("gives an assigned viewer only Add question on the question list", async () => {
    const mine = { user_id: 5, name: "V", email: "v@acme.com", sheet: { answers: {}, verdict: { decision: null, note: null } }, submitted_at: null };
    mountWithKit(READY, {}, { sheets: [mine], me: { id: 5, role: "viewer" }, canWrite: false });
    await screen.findByText("Why this role?");
    expect(screen.getByRole("button", { name: /add question/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /remove question 1/i })).not.toBeInTheDocument();
    expect(screen.getByPlaceholder(/what they said/i)).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest --run src/components/candidate/interview-kit-section.test.tsx`
Expected: the new tests FAIL (no sheet route calls, no verdict buttons, `window.confirm` path)

- [ ] **Step 3: Rewrite the section**

Key changes to `interview-kit-section.tsx` (keep generation/error/loading branches, the seeding-during-render pattern, `newQuestionId`, `errorMessage`, and the draft-with-AI block as they are):

```tsx
import { useCurrentUser } from "@/hooks/use-current-user";
import {
  EMPTY_SHEET, type InterviewSheet, type KitQuestion, type Rating, type VerdictDecision,
  useInterviewKit,
} from "@/hooks/use-interview-kit";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { FeedbackTable } from "./feedback-table";

const VERDICTS: { value: VerdictDecision; label: string }[] = [
  { value: "hire", label: "Hire" },
  { value: "no_hire", label: "No hire" },
  { value: "unsure", label: "Unsure" },
];
```

State and derived values inside the component:

```tsx
  const { kit, sheets, isLoading, isError, refetch, generate, patch, saveSheet, submitSheet, draftQuestion } =
    useInterviewKit(applicationId);
  const me = useCurrentUser();
  const myId = me.data?.id ?? null;
  const mySheetRead = sheets.find((s) => s.user_id === myId) ?? null;
  // A recruiter with no panel at all still gets a sheet (the server creates it on first save).
  const canWriteSheet = mySheetRead ? mySheetRead.submitted_at === null : (canWrite && sheets.length === 0);
  const isSubmitted = mySheetRead?.submitted_at != null;
  const frozen = sheets.some((s) => s.submitted_at !== null);
  const canEditQuestions = canWrite && !frozen;
  const canAppend = canWrite || mySheetRead !== null;

  const [sheet, setSheet] = useState<InterviewSheet>(EMPTY_SHEET);
  const [confirmOpen, setConfirmOpen] = useState(false);
  // Seed the sheet draft from the server the same way questions are seeded:
  // keyed on the sheet's identity, so a refetch never clobbers typing.
  const sheetKey = mySheetRead ? `${mySheetRead.user_id}:${mySheetRead.submitted_at}` : "none";
  const [seededSheetKey, setSeededSheetKey] = useState<string | null>(null);
  if (sheetKey !== seededSheetKey) {
    setSeededSheetKey(sheetKey);
    setSheet(mySheetRead?.sheet ?? EMPTY_SHEET);
  }
  const setAnswer = (id: string, fields: Partial<{ answer: string | null; rating: Rating | null }>) =>
    setSheet((s) => ({
      ...s,
      answers: { ...s.answers, [id]: { answer: null, rating: null, ...s.answers[id], ...fields } },
    }));
  const unanswered = draft.filter((q) => !sheet.answers[q.id]?.answer?.trim()).length;
  const isDirty =
    JSON.stringify(draft) !== JSON.stringify(kit?.questions ?? []) ||
    JSON.stringify(sheet) !== JSON.stringify(mySheetRead?.sheet ?? EMPTY_SHEET);
```

Save and submit:

```tsx
  function saveAll(onDone?: () => void) {
    const questionsChanged = JSON.stringify(draft) !== JSON.stringify(kit?.questions ?? []);
    const afterQuestions = () =>
      canWriteSheet
        ? saveSheet.mutate(sheet, {
            onError: (err) => toast.error(errorMessage(err, "Couldn't save answers")),
            onSuccess: onDone,
          })
        : onDone?.();
    if (questionsChanged && canAppend) {
      patch.mutate(draft, {
        onError: (err) => toast.error(errorMessage(err, "Couldn't save questions")),
        onSuccess: afterQuestions,
      });
    } else {
      afterQuestions();
    }
  }

  function doSubmit() {
    setConfirmOpen(false);
    saveAll(() =>
      submitSheet.mutate(undefined, {
        onSuccess: () => toast.success("Interview recorded"),
        onError: (err) => toast.error(errorMessage(err, "Answers saved, but submit failed — try again")),
      }));
  }

  function onSubmitClick() {
    if (unanswered > 0) setConfirmOpen(true);
    else doSubmit();
  }
```

Per-question row: the question textarea is editable only when `canEditQuestions` or (`canAppend` and the question is one the caller appended this session, i.e. not in `kit.questions`); otherwise render `<p className="flex-1 text-sm">{q.text}</p>`. Show `added by {q.added_by}` as a small muted tag when `q.added_by` is set. The Remove button renders when `canWrite`, with `disabled={frozen}` and `title={frozen ? "Questions are frozen once a sheet is submitted" : undefined}`. The answer box and rating buttons render when `canWriteSheet`, bound to `sheet.answers[q.id]`; when `isSubmitted`, render the submitted answer as text and the rating as a plain label. Legacy block per question:

```tsx
            {(q.answer || q.rating) && (
              <p className="text-xs text-muted-foreground">
                <span className="uppercase tracking-wide">Recorded before interviewer sheets</span>
                {q.answer && <> — {q.answer}</>}
                {q.rating && <> ({q.rating})</>}
              </p>
            )}
```

Verdict block, after the list, when `canWriteSheet`:

```tsx
        <div className="space-y-2 rounded border border-border p-2">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Verdict</p>
          <div className="flex gap-1">
            {VERDICTS.map((v) => (
              <Button key={v.value} type="button" size="sm"
                variant={sheet.verdict.decision === v.value ? "default" : "outline"}
                className="h-auto px-2 py-1 text-xs"
                onClick={() => setSheet((s) => ({ ...s, verdict: { ...s.verdict,
                  decision: s.verdict.decision === v.value ? null : v.value } }))}
              >
                {v.label}
              </Button>
            ))}
          </div>
          <Textarea aria-label="Verdict note" placeholder="One line on why…"
            value={sheet.verdict.note ?? ""}
            onChange={(e) => setSheet((s) => ({ ...s, verdict: { ...s.verdict, note: e.target.value || null } }))}
          />
        </div>
```

Buttons row: "Add question" when `canAppend`; draft-with-AI when `canAppend`; "Save answers" and "Submit interview" when `canWriteSheet` (hidden when `isSubmitted`). Regenerate is not a button today; nothing to disable.

Feedback table for writers: after the buttons, `{canWrite && sheets.length > 1 && <FeedbackTable questions={draft} sheets={sheets} />}` (component in Task 11; until then, stub the import with an empty component in this task and replace it in Task 11).

Confirm dialog, at the end of the section:

```tsx
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Submit with unanswered questions?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {unanswered} question(s) have no answer. Submit anyway?
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>Keep editing</Button>
            <Button onClick={doSubmit}>Submit anyway</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
```

- [ ] **Step 4: Run the section tests, the full suite, and TypeScript**

Run: `npx vitest --run && npx tsc --noEmit`
Expected: all pass, `tsc` clean. Remove the `submit` alias from the hook if it was kept in Task 8.

- [ ] **Step 5: Commit**

```bash
git add src/components/candidate/interview-kit-section.tsx src/components/candidate/interview-kit-section.test.tsx src/components/candidate/feedback-table.tsx src/hooks/use-interview-kit.ts
git commit -m "ui(interview-kit): answers, ratings and verdict on the interviewer's own sheet"
```

---

### Task 11: Feedback table

**Files:**
- Create/replace: `recruiter-frontend/src/components/candidate/feedback-table.tsx`
- Test: `recruiter-frontend/src/components/candidate/feedback-table.test.tsx`

**Interfaces:**
- Produces: `<FeedbackTable questions={KitQuestion[]} sheets={SheetRead[]} />`. One column per sheet (header `name ?? email`, `✓` when submitted), a verdict row on top, one row per question with the rating as a pill; questions unrated on every sheet are behind a "Show n unrated" toggle.

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { FeedbackTable } from "./feedback-table";

const Q = [
  { id: "q1", text: "Why?", source: "probe" as const, answer: null, rating: null },
  { id: "q2", text: "How?", source: "probe" as const, answer: null, rating: null },
];
const S = [
  { user_id: 1, name: "Ann", email: "ann@acme.com", submitted_at: "2026-09-14T10:00:00Z",
    sheet: { answers: { q1: { answer: "Fine", rating: "strong" as const } }, verdict: { decision: "hire" as const, note: null } } },
  { user_id: 2, name: null, email: "bob@acme.com", submitted_at: null,
    sheet: { answers: { q1: { answer: null, rating: "weak" as const } }, verdict: { decision: null, note: null } } },
];

describe("FeedbackTable", () => {
  it("renders one column per sheet with the verdict row on top", () => {
    render(<FeedbackTable questions={Q} sheets={S} />);
    expect(screen.getByRole("columnheader", { name: /Ann/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /bob@acme.com/ })).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveTextContent(/verdict/i);
    expect(rows[1]).toHaveTextContent(/hire/i);
  });

  it("shows ratings per question and hides unrated questions behind a toggle", async () => {
    render(<FeedbackTable questions={Q} sheets={S} />);
    expect(screen.getByRole("row", { name: /Why\?/ })).toHaveTextContent(/strong/);
    expect(screen.queryByRole("row", { name: /How\?/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /show 1 unrated/i }));
    expect(screen.getByRole("row", { name: /How\?/ })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest --run src/components/candidate/feedback-table.test.tsx`
Expected: FAIL (stub component renders nothing)

- [ ] **Step 3: Implement**

```tsx
import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { KitQuestion, Rating, SheetRead, VerdictDecision } from "@/hooks/use-interview-kit";

const RATING_CLASS: Record<Rating, string> = {
  strong: "border-emerald-500/60 text-emerald-300",
  adequate: "border-amber-500/60 text-amber-300",
  weak: "border-red-500/60 text-red-300",
};

const VERDICT_LABEL: Record<VerdictDecision, string> = {
  hire: "Hire", no_hire: "No hire", unsure: "Unsure",
};

interface Props {
  questions: KitQuestion[];
  sheets: SheetRead[];
}

export function FeedbackTable({ questions, sheets }: Props) {
  const [showUnrated, setShowUnrated] = useState(false);
  const rated = (q: KitQuestion) => sheets.some((s) => s.sheet.answers[q.id]?.rating);
  const unratedCount = questions.filter((q) => !rated(q)).length;
  const rows = showUnrated ? questions : questions.filter(rated);

  return (
    <section className="space-y-2">
      <h4 className="text-sm font-semibold">Feedback</h4>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr>
              <th scope="col" className="text-left font-normal text-muted-foreground">Question</th>
              {sheets.map((s) => (
                <th key={s.user_id} scope="col" className="text-left font-normal">
                  {s.name ?? s.email}{s.submitted_at && <span aria-label="submitted"> ✓</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr aria-label="Verdict">
              <th scope="row" className="text-left font-medium">Verdict</th>
              {sheets.map((s) => (
                <td key={s.user_id}>
                  {s.sheet.verdict.decision ? VERDICT_LABEL[s.sheet.verdict.decision] : "—"}
                  {s.sheet.verdict.note && (
                    <span className="block text-xs text-muted-foreground">{s.sheet.verdict.note}</span>
                  )}
                </td>
              ))}
            </tr>
            {rows.map((q) => (
              <tr key={q.id} aria-label={q.text}>
                <th scope="row" className="text-left font-normal">{q.text}</th>
                {sheets.map((s) => {
                  const a = s.sheet.answers[q.id];
                  return (
                    <td key={s.user_id} className="align-top">
                      {a?.rating ? (
                        <span className={`rounded border px-1.5 py-0.5 text-xs capitalize ${RATING_CLASS[a.rating]}`}>
                          {a.rating}
                        </span>
                      ) : "—"}
                      {a?.answer && (
                        <details className="text-xs text-muted-foreground">
                          <summary>answer</summary>{a.answer}
                        </details>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {unratedCount > 0 && (
        <Button variant="ghost" size="sm" onClick={() => setShowUnrated((v) => !v)}>
          {showUnrated ? `Hide ${unratedCount} unrated` : `Show ${unratedCount} unrated`}
        </Button>
      )}
    </section>
  );
}
```

- [ ] **Step 4: Run**

Run: `npx vitest --run src/components/candidate/feedback-table.test.tsx src/components/candidate/interview-kit-section.test.tsx && npx tsc --noEmit`
Expected: pass

- [ ] **Step 5: Commit**

```bash
git add src/components/candidate/feedback-table.tsx src/components/candidate/feedback-table.test.tsx
git commit -m "ui(interview-kit): side-by-side feedback table for recruiters"
```

---

### Task 12: Kanban badge

**Files:**
- Modify: `recruiter-frontend/src/components/kanban/candidate-card.tsx:119-124`
- Test: `recruiter-frontend/src/components/kanban/candidate-card.test.tsx`

- [ ] **Step 1: Write the failing test** (append to the existing `describe` using its `renderCard`/`baseApp` helpers)

```tsx
  it("shows sheet progress while scheduled with interviewers", () => {
    renderCard(baseApp({ stage: "scheduled", sheets_total: 3, sheets_submitted: 1 }));
    expect(screen.getByText("1/3 sheets in")).toBeInTheDocument();
  });

  it("shows no sheet progress without interviewers or after the round", () => {
    renderCard(baseApp({ stage: "scheduled", sheets_total: 0, sheets_submitted: 0 }));
    expect(screen.queryByText(/sheets in/)).not.toBeInTheDocument();
    renderCard(baseApp({ id: 69, stage: "interviewed", sheets_total: 2, sheets_submitted: 2 }));
    expect(screen.queryByText(/sheets in/)).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest --run src/components/kanban/candidate-card.test.tsx`
Expected: FAIL — text not found

- [ ] **Step 3: Implement**

In `candidate-card.tsx`, after the stage/time row:

```tsx
        {application.stage === "scheduled" && (application.sheets_total ?? 0) > 0 && (
          <span className="block text-xs text-muted-foreground">
            {application.sheets_submitted ?? 0}/{application.sheets_total} sheets in
          </span>
        )}
```

- [ ] **Step 4: Run and commit**

Run: `npx vitest --run src/components/kanban/candidate-card.test.tsx`
Expected: pass

```bash
git add src/components/kanban/candidate-card.tsx src/components/kanban/candidate-card.test.tsx
git commit -m "ui(kanban): show interviewer sheet progress on scheduled cards"
```

---

### Task 13: End-to-end two-interviewer flow

**Files:**
- Modify: `recruiter-frontend/e2e/interview-kit.spec.ts` (from line 118, the UI flow)

- [ ] **Step 1: Extend the spec**

After `await waitForKitReady(page, appId);`, replace the UI flow with:

```ts
    // Second interviewer: created through the admin users API in this
    // spec's own fixture, assigned alongside the admin running the test.
    const stamp = Date.now();
    const created = await page.request.post("/api/users", {
      data: { email: `e2e-interviewer-${stamp}@example.test`, name: "Second Interviewer",
              role: "viewer", password: "pw-12345678" },
    });
    expect(created.ok()).toBeTruthy();
    const secondId = (await created.json()).id as number;
    const meId = (await (await page.request.get("/api/auth/me")).json()).id as number;
    const assign = await page.request.put(`/api/applications/${appId}/interviewers`, {
      data: { user_ids: [meId, secondId] },
    });
    expect(assign.ok()).toBeTruthy();

    // Admin fills and submits their sheet in the UI.
    await page.goto(`/applications/${appId}?tab=interview`);
    const firstAnswer = page.getByPlaceholder(/what they said/i).first();
    await expect(firstAnswer).toBeVisible({ timeout: 60_000 });
    await firstAnswer.fill("Ran the platform for two years.");
    await page.getByRole("button", { name: /^hire$/i }).click();
    await page.getByRole("button", { name: /submit interview/i }).click();
    const dialog = page.getByRole("dialog");
    if (await dialog.isVisible().catch(() => false)) {
      await dialog.getByRole("button", { name: /submit anyway/i }).click();
    }
    await expect(page.getByText(/interview recorded/i)).toBeVisible();

    // One of two sheets in: still scheduled, and the card says so.
    await pollStage(page, appId, "scheduled", 5_000);
    await expect(page.getByText("1/2 sheets in")).toBeVisible({ timeout: 10_000 }).catch(() => {});

    // Second interviewer submits through the API (a separate browser
    // context would be the purist option; the rule under test is the
    // server's, and the API is the same path the UI takes).
    const ctx = await page.context().browser()!.newContext();
    const other = await ctx.newPage();
    await other.goto("/login");
    await other.getByRole("textbox", { name: "Email" }).fill(`e2e-interviewer-${stamp}@example.test`);
    await other.getByRole("textbox", { name: "Password" }).fill("pw-12345678");
    await other.getByRole("button", { name: /sign in/i }).click();
    await expect(other).toHaveURL(/\/jobs/);
    const submit = await other.request.post(`/api/applications/${appId}/interview-kit/sheet/submit`);
    expect(submit.ok(), await submit.text()).toBeTruthy();
    await ctx.close();

    await pollStage(page, appId, "interviewed", 30_000);
```

Remove the earlier `page.once("dialog", …)` line and the old `/interview-kit/submit` usage. The `1/2 sheets in` assertion is on the candidate page, where the card is not rendered; drop that line or navigate to `/jobs/${jobId}` first and assert there, then return.

- [ ] **Step 2: Run against a rebuilt stack**

```bash
cd /home/walidboudiche/recruiter-agent && docker compose up -d --build backend frontend
cd recruiter-frontend && set -a && . ../.env && set +a && \
  E2E_DEFAULT_EMAIL="$RECRUITER_DEFAULT_ACCOUNT_EMAIL" E2E_DEFAULT_PASSWORD="$RECRUITER_DEFAULT_ACCOUNT_PASSWORD" \
  npx playwright test e2e/interview-kit.spec.ts
```

Expected: pass. It creates one job, one candidate and one user; delete them afterwards with the same SQL cleanup used for E2E jobs, plus `delete from users where email like 'e2e-interviewer-%'`.

- [ ] **Step 3: Commit**

```bash
git add e2e/interview-kit.spec.ts
git commit -m "test(e2e): two interviewers, stage moves only when both sheets are in"
```

---

### Task 14: Decisions record and permissions doc

**Files:**
- Create: `docs/superpowers/specs/2026-09-14-multi-interviewer-decisions.md`

- [ ] **Step 1: Write the record** in the style of `2026-09-10-interview-kits-decisions.md`: what changed against this plan during the build, constraints reversed, follow-ups. Minimum content on day one:

```markdown
# Multiple interviewers — decisions and follow-ups

Date: 2026-09-14
Status: record
Design: `2026-09-14-multi-interviewer-design.md`
Plan: `../plans/2026-09-14-multi-interviewer.md`

## Deviations from the plan
(filled in by whoever executes; "none" is a valid entry)

## Follow-ups
1. Email or calendar-invite interviewers on assignment (out of scope by design).
2. Per-question interviewer tagging for split panels.
3. Multiple rounds with separate question sets.
4. The legacy per-question `answer`/`rating` fields and `submitted_at` can be
   dropped once no kit in any deployment carries them.
5. The e2e second-interviewer user is never deleted (no DELETE on users by
   design); clean it up with the E2E job cleanup.
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-09-14-multi-interviewer-decisions.md
git commit -m "docs(interview-kit): decisions record for multiple interviewers"
```

---

## Self-review

**Spec coverage.** Data model → Task 1. Freeze → Task 5. Assignments GET/PUT with 409/422 → Task 3. Sheets GET filter / PATCH / submit, 404/409, recruiter auto-create, prune → Task 4. Questions append with `added_by`, interviewer 403 → Task 5. Viewer exception + docstring → Task 6. Chat agent filter → no task: `grep -rn interview src/recruiter/agent/` finds no tool that reads the kit, so there is nothing to filter; Task 14's record should say so. Stage rule, manual move sets `closed_at`, late submit no-op → Task 4. Visibility table → Tasks 2 and 4. Kanban `n/m` → Tasks 7 and 12. SSE on submit and on assignment change → Task 4 publishes on submit; Task 3 publishes the same event at the end of `put_interviewers`, and Task 8's mutation `onSuccess` invalidates client-side as well. UI picker, verdict, submit dialog, feedback table, freeze tooltip, legacy → Tasks 9–11. E2E → Task 13. Migration order → task order.

**Placeholders.** None; every step carries code or an exact command.

**Type consistency.** `InterviewSheet` / `SheetRead` names match between `schemas/interview.py`, `use-interview-kit.ts`, and the tests. `load_assignments` lives in `api/interviewers.py` and is imported by `api/interview.py` (no cycle: `interviewers.py` imports only `deps` and `models`). `_read` is the single serializer for kit responses. `sheets_total`/`sheets_submitted` names match backend schema, `ApplicationRead` TS type, and the card test.
