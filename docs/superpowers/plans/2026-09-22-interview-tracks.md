# Interview Tracks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A round can hold several parallel interviews ("tracks", e.g. Technical + RH screen), each with its own questions, panel and sheets; the round closes when every track is done.

**Architecture:** No new table: a track is an `interview_kits` row plus the `interview_assignments` rows sharing its `(application, round, track)`, with the track key derived from the template (`t<id>` or `default`). Code that assumes "the kit of the round" moves to "the round's kits": pure rules first, then reads, writes, panel, the round lifecycle and an add/remove-track router. The frontend splits the kit section into a per-track view shown in tabs when a round has two or more tracks, and makes the round-start picker and the panel track-aware.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Postgres 16, pytest; React 18, TanStack Query, Radix UI, Vitest + Testing Library + msw.

**Spec:** `docs/superpowers/specs/2026-09-22-interview-tracks-design.md`

## Global Constraints

- **One-track rounds behave and look exactly as today.** Every pre-existing test passes. Pre-existing test files change only where a task says so: `tests/api/conftest.py` gains a fixture (Task 2); `recruiter-frontend/src/components/candidate/interview-kit-section.test.tsx`'s `mountWithKit` gains optional fields and handlers (Task 8); `schedule-round-dialog.test.tsx` is rewritten because the picker becomes multi-select by design (Task 9). Other test files only gain new tests. No expected value in any pre-existing test changes.
- Track key: exactly `f"t{template_id}"` for a templated track and `"default"` (`DEFAULT_TRACK`) for the no-template track; derived once at creation, never changed.
- The query parameter naming a track is `track` everywhere (`?track=t5`).
- Names, exactly — backend: `track_key`, `kits_in_round` (`pipeline/kit_store.py`); `rows_in_track`, `round_complete`, `visible_kits` (`pipeline/interview_sheets.py`); `resolve_track`, `own_row`, `kit_for_caller`, `target_track` (`api/kit_tracks.py`); `NO_LLM_PROVIDER`, `TrackRead`, `dispatch_generation` (`api/interview.py`); `create_track`, `adopt_orphan_rows`, `start_round`, `open_next_round` (`api/round_tracks.py`). Frontend: `TrackRead`, `tracksOf`, `useTrackKitActions`, `useTrackMutations`, `sheetHasContent` (`hooks/use-interview-kit.ts`); `TrackKitView`, `errorMessage` (`components/candidate/track-kit-view.tsx`); `AddTrackDialog` (`components/candidate/add-track-dialog.tsx`).
- Every track mutation — scheduling, adding or removing a track, panel edits, sheet save and submit — runs under the application row lock (`session.get(..., with_for_update=True)` or `_load_application(..., for_update=True)`), as phase 1 established.
- New routers register with `_api_router.include_router(...)` in `src/recruiter/main.py`, never `app.include_router(...)`; `tests/api/test_viewer_matrix.py` fails any route without the viewer guard.
- Frontend: Radix `Select`/`Tabs` from `@/components/ui/*`, native `<input type="checkbox">`, semantic Tailwind tokens only (light and dark themes).
- **Bash timeouts:** pass `timeout: 400000` on every Bash call that runs `uv run pytest -q`, the full `npx vitest --run`, or `npm run build`. The harness backgrounds calls over 120 s otherwise and the agent stalls.
- Ruff: `uv run ruff check src/ tests/` is 466 at the start. It may grow only by B008 findings from FastAPI `Depends(...)` defaults in new handlers. Line length 100; isort; imports at the top of files.
- Every commit message ends with:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

---

## File Structure

**Created**
- `alembic/versions/20260924_000000_interview_tracks.py` — re-key templated kits; swap the assignment unique key.
- `src/recruiter/api/kit_tracks.py` — pure request→track resolution shared by the routers.
- `src/recruiter/api/round_tracks.py` — a round's tracks on scheduling, rescheduling and reopening.
- `src/recruiter/api/interview_tracks.py` — `POST`/`DELETE /interview-tracks`.
- `recruiter-frontend/src/components/candidate/track-kit-view.tsx` — one track's kit and sheet (extracted from the section).
- `recruiter-frontend/src/components/candidate/add-track-dialog.tsx`.
- Tests: `tests/unit/test_kit_tracks.py`, `tests/api/test_interview_tracks_read.py`, `tests/api/test_interview_tracks_write.py`, `tests/api/test_interview_tracks_panel.py`, `tests/api/test_interview_track_rounds.py`, `tests/api/test_interview_tracks_api.py`.

**Modified**
- Backend: `models/interview_assignment.py`, `models/interview_kit_row.py` (comment), `pipeline/kit_store.py`, `pipeline/interview_sheets.py`, `schemas/interview.py`, `schemas/application.py`, `api/interview.py`, `api/interviewers.py`, `api/applications.py`, `main.py`.
- Frontend: `hooks/use-interview-kit.ts`, `hooks/use-interviewers.ts`, `hooks/use-interview-templates.ts`, `hooks/use-application-mutations.ts`, `components/candidate/interview-kit-section.tsx`, `components/candidate/interviewers-picker.tsx`, `components/candidate/schedule-round-dialog.tsx`, `components/candidate/action-bar.tsx`, `routes/application-detail.tsx`.

---

### Task 1: Migration, one track per person, and the pure track rules

**Files:**
- Create: `alembic/versions/20260924_000000_interview_tracks.py`
- Modify: `src/recruiter/models/interview_assignment.py`, `src/recruiter/models/interview_kit_row.py`, `src/recruiter/pipeline/kit_store.py`, `src/recruiter/pipeline/interview_sheets.py`
- Test: `tests/unit/test_kit_store.py`, `tests/unit/test_interview_sheets_rules.py`, `tests/unit/test_interview_assignment_model.py`, `tests/api/test_kit_migration.py`

**Interfaces:**
- Produces: `track_key(template_id: int | None) -> str`; `rows_in_track(rows, round_number: int, track: str) -> list[InterviewAssignment]`; `round_complete(kits, rows) -> bool`; unique constraint `uq_interview_assignment_app_user_round` on `(application_id, user_id, round)`; alembic revision `f3b7d2e8a915`.

- [ ] **Step 1: Record the ruff baseline**

Run: `uv run ruff check src/ tests/ 2>&1 | grep "^Found"` — expected `Found 466 errors.` Note it in your report.

- [ ] **Step 2: Write the failing unit tests**

In `tests/unit/test_kit_store.py`, change the import to `from recruiter.pipeline.kit_store import DEFAULT_TRACK, apply_content, content_of, track_key` and append:

```python
def test_a_track_key_is_derived_from_its_template() -> None:
    assert track_key(None) == DEFAULT_TRACK == "default"
    assert track_key(7) == "t7"
```

In `tests/unit/test_interview_sheets_rules.py`, change the models import to `from recruiter.models import InterviewAssignment, InterviewKitRow, Role, User`, add `round_complete` and `rows_in_track` to the `recruiter.pipeline.interview_sheets` import (keep it sorted), and append:

```python
def _kit(track: str) -> InterviewKitRow:
    return InterviewKitRow(application_id=1, round=1, track=track, status="ready", questions=[])


def _on(track: str, uid: int, submitted: bool, round_number: int = 1) -> InterviewAssignment:
    row = _row(uid, submitted, round_number)
    row.track = track
    return row


def test_rows_in_track_is_one_round_and_one_track() -> None:
    rows = [_on("tech", 1, False), _on("rh", 2, False), _on("tech", 3, False, round_number=2)]
    assert rows_in_track(rows, 1, "tech") == [rows[0]]
    assert rows_in_track(rows, 2, "tech") == [rows[2]]
    assert rows_in_track(rows, 1, "nope") == []


def test_a_round_closes_only_when_every_track_is_staffed_and_submitted() -> None:
    kits = [_kit("tech"), _kit("rh")]
    assert not round_complete([], [_on("tech", 1, True)]), "no kit: nothing to close"
    assert not round_complete(kits, []), "nobody assigned"
    assert not round_complete(kits, [_on("tech", 1, True)]), (
        "an unstaffed RH track must not be skipped when the technical panel finishes")
    assert not round_complete(kits, [_on("tech", 1, True), _on("rh", 2, False)])
    assert round_complete(kits, [_on("tech", 1, True), _on("rh", 2, True)])


def test_a_one_track_round_closes_as_before() -> None:
    one = [_kit("default")]
    assert round_complete(one, [_on("default", 1, True), _on("default", 2, True)])
    assert not round_complete(one, [_on("default", 1, True), _on("default", 2, False)])
```

In `tests/unit/test_interview_assignment_model.py`, append:

```python
@pytest.mark.asyncio
async def test_a_person_is_on_one_track_per_round(db_session_with_schema: AsyncSession) -> None:
    """Tracks run in parallel, but one interviewer sits on at most one of
    them in a round. The same person may be on another track next round."""
    app_id, user_id = await _seed(db_session_with_schema)
    db_session_with_schema.add(InterviewAssignment(
        application_id=app_id, user_id=user_id, round=1, track="tech"))
    db_session_with_schema.add(InterviewAssignment(
        application_id=app_id, user_id=user_id, round=2, track="rh"))
    await db_session_with_schema.commit()
    db_session_with_schema.add(InterviewAssignment(
        application_id=app_id, user_id=user_id, round=1, track="rh"))
    with pytest.raises(IntegrityError):
        await db_session_with_schema.commit()
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_kit_store.py tests/unit/test_interview_sheets_rules.py tests/unit/test_interview_assignment_model.py -q`
Expected: FAIL — `ImportError` for `track_key`/`round_complete`/`rows_in_track`, and the assignment test does not raise.

- [ ] **Step 4: Implement the rules and the constraint**

In `src/recruiter/pipeline/kit_store.py`, after `DEFAULT_TRACK = "default"`:

```python
def track_key(template_id: int | None) -> str:
    """A track's key, derived once from its template when the track is
    created and never changed: `t<template_id>`, or `default` for the
    no-template track. Because (application, round, track) is unique, this
    alone guarantees one track per template per round."""
    return DEFAULT_TRACK if template_id is None else f"t{template_id}"
```

In `src/recruiter/pipeline/interview_sheets.py`, after `rows_in_round`:

```python
def rows_in_track(
    rows: Iterable[InterviewAssignment], round_number: int, track: str,
) -> list[InterviewAssignment]:
    """The assignments on one track of one round — the panel for one kit."""
    return [r for r in rows if r.round == round_number and r.track == track]
```

and after `all_submitted`:

```python
def round_complete(
    kits: Iterable[InterviewKitRow], rows: Iterable[InterviewAssignment],
) -> bool:
    """Whether a round can close on its own: it has at least one kit, every
    kit's track has at least one interviewer, and every interviewer in the
    round has submitted. Callers pass ONE round's kits and rows.

    The staffing clause is what stops an RH track nobody was assigned to
    from being silently skipped the moment the technical panel finishes."""
    kits, rows = list(kits), list(rows)
    if not kits or not rows:
        return False
    staffed = {r.track for r in rows}
    return all(k.track in staffed for k in kits) and all(
        r.submitted_at is not None for r in rows
    )
```

In `src/recruiter/models/interview_assignment.py`, replace the unique constraint with

```python
        # One track per interviewer per round (phase 3): a person sits on at
        # most one of a round's parallel interviews.
        UniqueConstraint("application_id", "user_id", "round",
                         name="uq_interview_assignment_app_user_round"),
```

and replace the comment above the `track` column with

```python
    # Which track within the round — the kit this sheet's answers are keyed
    # against. At most one per person per round (see the constraint above).
```

In `src/recruiter/models/interview_kit_row.py`, replace the two comment lines above the `track` column with

```python
    # `t<template_id>` for a templated track, `default` without a template
    # (pipeline/kit_store.track_key); derived at creation, never changed.
```

- [ ] **Step 5: Write the migration**

Run `uv run alembic heads` — expected `e6f2a9c4b1d3 (head)`. Create `alembic/versions/20260924_000000_interview_tracks.py`:

```python
"""interview tracks: re-key templated kits, one track per interviewer per round

Revision ID: f3b7d2e8a915
Revises: e6f2a9c4b1d3
Create Date: 2026-09-24 00:00:00.000000

Phase 3 derives every kit's track key from its template: `t<template_id>`,
or `default` without one. Phase-2 kits built from a template were created
under `default`; they and their panel rows are re-keyed so every kit
follows the rule. An interviewer is on at most one track per round, so the
assignment unique key drops `track`. Every existing row is on `default`,
so no existing data can violate it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f3b7d2e8a915'
down_revision: Union[str, None] = 'e6f2a9c4b1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Panel rows first, while their kit still reads `default`.
    op.execute(sa.text(
        "UPDATE interview_assignments AS a"
        " SET track = 't' || k.template_id"
        " FROM interview_kits AS k"
        " WHERE k.template_id IS NOT NULL AND k.track = 'default'"
        " AND a.application_id = k.application_id AND a.round = k.round"
        " AND a.track = 'default'"
    ))
    op.execute(sa.text(
        "UPDATE interview_kits SET track = 't' || template_id"
        " WHERE template_id IS NOT NULL AND track = 'default'"
    ))
    op.drop_constraint(
        "uq_interview_assignment_app_user_round_track", "interview_assignments",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_interview_assignment_app_user_round", "interview_assignments",
        ["application_id", "user_id", "round"],
    )


def downgrade() -> None:
    # Pre-phase-3 code reads one kit per round; refuse rather than lose one.
    multi = op.get_bind().execute(sa.text(
        "SELECT application_id, round FROM interview_kits"
        " GROUP BY application_id, round HAVING count(*) > 1 LIMIT 1"
    )).first()
    if multi is not None:
        raise RuntimeError(
            f"cannot downgrade: application {multi[0]} round {multi[1]} has more than "
            "one interview track; remove the extra tracks first"
        )
    op.execute(sa.text("UPDATE interview_assignments SET track = 'default'"))
    op.execute(sa.text("UPDATE interview_kits SET track = 'default'"))
    op.drop_constraint(
        "uq_interview_assignment_app_user_round", "interview_assignments", type_="unique",
    )
    op.create_unique_constraint(
        "uq_interview_assignment_app_user_round_track", "interview_assignments",
        ["application_id", "user_id", "round", "track"],
    )
```

- [ ] **Step 6: Write the migration test**

In `tests/api/test_kit_migration.py`, add `import pytest` to the imports, `TRACKS = "f3b7d2e8a915"   # migration D: interview tracks` beside the other revision constants, and append:

```python
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
            " VALUES ('paste','C','[]','[]','[]','[]',now(),now())"))
        user_id = conn.execute(sa.text(
            "INSERT INTO users (email, role, is_active, created_at, updated_at)"
            " VALUES ('i@acme.com', 'viewer', true, now(), now()) RETURNING id")).scalar_one()
        app_ids = [conn.execute(sa.text(
            "INSERT INTO applications (job_id, candidate_id, stage, interview_round,"
            " created_at, updated_at)"
            " SELECT (SELECT id FROM jobs LIMIT 1), (SELECT id FROM candidates LIMIT 1),"
            " 'scheduled', 1, now(), now() RETURNING id")).scalar_one() for _ in range(2)]
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
```

- [ ] **Step 7: Run everything touched**

Run: `uv run pytest tests/unit/test_kit_store.py tests/unit/test_interview_sheets_rules.py tests/unit/test_interview_assignment_model.py tests/api/test_kit_migration.py -q` (timeout 400000) — expected all PASS.
Run: `uv run alembic heads` — expected `f3b7d2e8a915 (head)`.

- [ ] **Step 8: Whole suite, ruff, commit**

Run: `uv run pytest -q` (timeout 400000) — all pass. `uv run ruff check src/ tests/` — 466.

```bash
git add alembic/versions src/recruiter/models src/recruiter/pipeline tests/unit tests/api/test_kit_migration.py
git commit -m "feat(interview-kit): track keys, one track per interviewer, and the closing rule

A track's key is derived from its template (t<id>, or default without
one); the migration re-keys phase-2 templated kits and their panels to
match, and an interviewer now sits on at most one track per round. A
round can close on its own only when every track is staffed and every
sheet is in, so an unstaffed RH track cannot be silently skipped.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Reading and closing a round with several tracks

**Files:**
- Modify: `src/recruiter/pipeline/kit_store.py`, `src/recruiter/pipeline/interview_sheets.py`, `src/recruiter/schemas/interview.py`, `src/recruiter/api/interview.py`, `src/recruiter/api/applications.py`, `tests/api/conftest.py`
- Test: `tests/unit/test_interview_sheets_rules.py`, `tests/api/test_interview_tracks_read.py`

**Interfaces:**
- Consumes: `rows_in_track`, `round_complete` (Task 1).
- Produces: `async kits_in_round(session, app_row, *, round: int | None = None) -> list[InterviewKitRow]` (creation order); `visible_kits(kits, rows, *, user, current_round) -> list[InterviewKitRow]`; `mark_interviewed(app_row, kits: Iterable[InterviewKitRow], now)` (was one kit); `SheetRead.track: str`; `TrackRead(track, template_id, template_name, kit)`; `InterviewKitRead.tracks: list[TrackRead]`; test fixtures `seed_tracks` and `login_as` (and the constant `TRACKS_PW`) in `tests/api/conftest.py`.

- [ ] **Step 1: Add the multi-track seeding fixture**

In `tests/api/conftest.py`, extend the imports (keep them sorted) with `from datetime import UTC, datetime`, `from recruiter.auth.passwords import hash_password`, and add `InterviewAssignment, InterviewKitRow, Job, Role, User` to the `recruiter.models` import. Append:

```python
TRACKS_PW = "pw-12345678"


@pytest.fixture
def seed_tracks():
    """Factory for a SCHEDULED application whose live round has two tracks,
    `tech` (question q1) and `rh` (question r1), created in that order.

    `panel` maps a track to its interviewers' emails (VIEWER users with
    password TRACKS_PW, created here); `submitted` lists the emails whose
    sheet is already submitted. Returns (application id, {email: user id}).
    Use with api_client or api_client_unauth: it writes through the engine
    that fixture installed.
    """

    async def _make(
        *, panel: dict[str, list[str]] | None = None, submitted: tuple[str, ...] = (),
    ) -> tuple[int, dict[str, int]]:
        if panel is None:
            panel = {"tech": ["tech@acme.com"], "rh": ["rh@acme.com"]}
        engine = app.dependency_overrides[get_engine_dep]()
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
        async with SessionLocal() as session:
            job = Job(title="Backend", description="x", criteria=[])
            session.add(job)
            await session.flush()
            cand = Candidate(source_type="paste", full_name="Marie", email="m@example.com")
            session.add(cand)
            await session.flush()
            app_row = Application(
                job_id=job.id, candidate_id=cand.id, stage=Stage.SCHEDULED, score=80,
            )
            session.add(app_row)
            await session.flush()
            for track, qid in (("tech", "q1"), ("rh", "r1")):
                session.add(InterviewKitRow(
                    application_id=app_row.id, round=1, track=track, status="ready",
                    questions=[{"id": qid, "text": f"{track} question", "source": "baseline"}],
                ))
                await session.flush()  # ids in creation order
            users: dict[str, int] = {}
            for track, emails in panel.items():
                for email in emails:
                    user = User(email=email, role=Role.VIEWER, is_active=True,
                                password_hash=hash_password(TRACKS_PW))
                    session.add(user)
                    await session.flush()
                    users[email] = user.id
                    session.add(InterviewAssignment(
                        application_id=app_row.id, user_id=user.id, round=1, track=track,
                        submitted_at=datetime.now(UTC) if email in submitted else None,
                    ))
            await session.commit()
            return app_row.id, users

    return _make


@pytest.fixture
def login_as():
    """Log a client in as one of `seed_tracks`' interviewers (password
    TRACKS_PW). Tests that log in several times should also reset the login
    rate limiter, as test_interview_freeze_api.py does."""

    async def _login(client: AsyncClient, email: str) -> None:
        await client.post("/api/auth/logout")
        r = await client.post(
            "/api/auth/login/password", json={"email": email, "password": TRACKS_PW},
        )
        assert r.status_code == 204, r.text

    return _login
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/unit/test_interview_sheets_rules.py` (add `visible_kits` to its import):

```python
def test_the_blind_rule_is_per_track() -> None:
    """An RH interviewer never sees a technical sheet, before or after
    submitting their own; within their track the phase-1 rule holds."""
    rows = [_on("tech", 1, True), _on("rh", 2, True), _on("rh", 3, False), _on("rh", 4, True)]
    assert visible_sheets(rows, user=_user(3, Role.VIEWER), current_round=1) == [rows[2]]
    assert visible_sheets(rows, user=_user(2, Role.VIEWER), current_round=1) == [rows[1], rows[3]]
    assert visible_sheets(rows, user=_user(9, Role.RECRUITER), current_round=1) == rows


def test_an_interviewer_sees_only_their_tracks_kit() -> None:
    kits = [_kit("tech"), _kit("rh")]
    rows = [_on("tech", 1, False), _on("rh", 2, False)]
    assert visible_kits(kits, rows, user=_user(2, Role.VIEWER), current_round=1) == [kits[1]]
    assert visible_kits(kits, rows, user=_user(9, Role.RECRUITER), current_round=1) == kits
    assert visible_kits(kits, rows, user=_user(7, Role.VIEWER), current_round=1) == kits, (
        "someone on no track sees every track, as before tracks existed")
```

Create `tests/api/test_interview_tracks_read.py`:

```python
"""Reading, and closing, a round with two tracks (phase 3)."""
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from recruiter.api.candidates import get_engine_dep
from recruiter.auth.passwords import hash_password
from recruiter.main import app
from recruiter.models import InterviewAssignment, InterviewKitRow, Role, User

KIT = "/api/applications/{}/interview-kit"


@pytest.fixture(autouse=True)
def _reset_limiter():
    # Several logins per test; without a reset the shared 5/min login
    # budget trips across tests and files (see rate_limit.py).
    from recruiter.api.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


async def _kits(app_id: int) -> list[InterviewKitRow]:
    SessionLocal = async_sessionmaker(app.dependency_overrides[get_engine_dep](),
                                      expire_on_commit=False)
    async with SessionLocal() as s:
        return list((await s.execute(
            select(InterviewKitRow).where(InterviewKitRow.application_id == app_id)
            .order_by(InterviewKitRow.id))).scalars().all())


@pytest.mark.asyncio
async def test_a_recruiter_sees_every_track_in_creation_order(
    api_client: AsyncClient, seed_tracks,
) -> None:
    app_id, _ = await seed_tracks()
    body = (await api_client.get(KIT.format(app_id))).json()

    assert [t["track"] for t in body["tracks"]] == ["tech", "rh"]
    assert [q["id"] for q in body["tracks"][1]["kit"]["questions"]] == ["r1"]
    assert body["kit"]["questions"][0]["id"] == "q1", "compat kit: the round's first track"
    assert sorted(s["track"] for s in body["sheets"]) == ["rh", "tech"]


@pytest.mark.asyncio
async def test_an_interviewer_sees_only_their_own_track(
    api_client_unauth: AsyncClient, seed_tracks, login_as,
) -> None:
    app_id, _ = await seed_tracks(
        panel={"tech": ["tech@acme.com"], "rh": ["rh@acme.com", "rh2@acme.com"]},
        submitted=("tech@acme.com", "rh@acme.com", "rh2@acme.com"),
    )
    await login_as(api_client_unauth, "rh@acme.com")
    body = (await api_client_unauth.get(KIT.format(app_id))).json()

    assert [t["track"] for t in body["tracks"]] == ["rh"]
    assert body["kit"]["questions"][0]["id"] == "r1", "compat kit: the caller's own track"
    assert sorted(s["email"] for s in body["sheets"]) == ["rh2@acme.com", "rh@acme.com"], (
        "after submitting, the RH panel's sheets — never the technical one")


@pytest.mark.asyncio
async def test_the_round_waits_for_an_unstaffed_track(
    api_client_unauth: AsyncClient, seed_tracks, login_as,
) -> None:
    app_id, _ = await seed_tracks(panel={"tech": ["tech@acme.com"]})
    await login_as(api_client_unauth, "tech@acme.com")
    r = await api_client_unauth.post(f"{KIT.format(app_id)}/sheet/submit")
    assert r.status_code == 200, r.text
    stage = (await api_client_unauth.get(f"/api/applications/{app_id}")).json()["stage"]
    assert stage == "scheduled", "the RH track has nobody on it yet"

    SessionLocal = async_sessionmaker(app.dependency_overrides[get_engine_dep](),
                                      expire_on_commit=False)
    async with SessionLocal() as s:
        # Same password as seed_tracks' interviewers, so login_as works.
        carol = User(email="carol@acme.com", role=Role.VIEWER, is_active=True,
                     password_hash=hash_password("pw-12345678"))
        s.add(carol)
        await s.flush()
        s.add(InterviewAssignment(application_id=app_id, user_id=carol.id, round=1, track="rh"))
        await s.commit()

    await login_as(api_client_unauth, "carol@acme.com")
    assert (await api_client_unauth.post(f"{KIT.format(app_id)}/sheet/submit")).status_code == 200
    stage = (await api_client_unauth.get(f"/api/applications/{app_id}")).json()["stage"]
    assert stage == "interviewed"
    assert all(k.closed_at for k in await _kits(app_id)), "closing stamps every track"


@pytest.mark.asyncio
async def test_marking_interviewed_by_hand_closes_every_track(
    api_client: AsyncClient, seed_tracks,
) -> None:
    app_id, _ = await seed_tracks()
    r = await api_client.patch(f"/api/applications/{app_id}", json={"stage": "interviewed"})
    assert r.status_code == 200, r.text
    assert all(k.closed_at for k in await _kits(app_id))
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_interview_sheets_rules.py tests/api/test_interview_tracks_read.py -q` (timeout 400000)
Expected: FAIL — `visible_kits` missing; `tracks` absent from the response; the round closes with an unstaffed track (or not all kits stamped).

- [ ] **Step 4: Implement**

`src/recruiter/pipeline/kit_store.py` — after `kit_for`:

```python
async def kits_in_round(
    session: AsyncSession, app_row: Application, *, round: int | None = None,
) -> list[InterviewKitRow]:
    """Every kit (track) of one round — the live round unless `round` is
    given — in creation order, the order tracks are shown in."""
    number = app_row.interview_round if round is None else round
    return list((await session.execute(
        select(InterviewKitRow)
        .where(InterviewKitRow.application_id == app_row.id,
               InterviewKitRow.round == number)
        .order_by(InterviewKitRow.id)
    )).scalars().all())
```

`src/recruiter/schemas/interview.py` — in `SheetRead`, after `round`:

```python
    # Which track of that round. An interviewer is on one track per round,
    # so (round, track) names the kit these answers are keyed against.
    track: str = "default"
```

`src/recruiter/pipeline/interview_sheets.py`:

1. In `visible_sheets`, add this paragraph to the end of the docstring:

```
    Within a round the rule is scoped to the caller's TRACK (phase 3): an
    RH interviewer never sees a technical sheet, before or after submitting
    their own.
```

and after `if own is None: return []` insert:

```python
    rows = [r for r in rows if r.track == own.track]
```

2. Add after `visible_sheets`:

```python
def visible_kits(
    kits: Iterable[InterviewKitRow], rows: Iterable[InterviewAssignment], *,
    user: User, current_round: int,
) -> list[InterviewKitRow]:
    """The live round's tracks a caller may see. Recruiters and admins see
    every track. An interviewer sees only their own track's kit, so an RH
    interviewer is never shown the technical questions. Someone on no
    track of the live round sees every track, as before tracks existed."""
    kits = list(kits)
    if can_edit_questions(user):
        return kits
    own = next(
        (r for r in rows_in_round(rows, current_round) if r.user_id == user.id), None,
    )
    if own is None:
        return kits
    return [k for k in kits if k.track == own.track]
```

3. Replace `mark_interviewed` with:

```python
def mark_interviewed(
    app_row: Application, kits: Iterable[InterviewKitRow], now: datetime,
) -> None:
    """Close the round: move the application to INTERVIEWED and stamp
    closed_at on every kit (track) in it. Shared by the automatic rule
    (close_round_if_complete) and the recruiter's manual override in
    patch_application, so both paths stamp the same fields the same way."""
    app_row.stage = Stage.INTERVIEWED
    app_row.interviewed_at = now
    for kit_row in kits:
        kit_row.closed_at = now.isoformat()
```

4. In `close_round_if_complete`, change the first docstring sentence to "Close the round if `app_row` is SCHEDULED and `round_complete` holds for its live round — every track staffed, every sheet submitted. Returns True iff it did." and replace the body after the lazy imports with:

```python
    from recruiter.api.interviewers import load_assignments
    from recruiter.pipeline.kit_store import kits_in_round

    if app_row.stage != Stage.SCHEDULED:
        return False
    kits = await kits_in_round(session, app_row)
    rows = rows_in_round(
        await load_assignments(session, app_row.id), app_row.interview_round,
    )
    if not round_complete(kits, rows):
        return False
    mark_interviewed(app_row, kits, datetime.now(UTC))
    return True
```

`src/recruiter/api/interview.py`:

1. Replace `InterviewKitRead` with:

```python
class TrackRead(BaseModel):
    track: str
    template_id: int | None = None
    template_name: str | None = None
    kit: InterviewKit


class InterviewKitRead(BaseModel):
    # Kept for one-track clients: the caller's own track if they are on one,
    # otherwise the round's first track. New clients read `tracks`.
    kit: InterviewKit | None
    template_name: str | None = None
    # Every track of the live round the caller may see, in creation order —
    # see pipeline/interview_sheets.visible_kits.
    tracks: list[TrackRead] = Field(default_factory=list)
    # Filtered per caller — see pipeline/interview_sheets.visible_sheets.
    sheets: list[SheetRead] = Field(default_factory=list)
```

2. In `_sheets_for`, add `track=r.track,` after `round=r.round,`.

3. Replace `_read` with:

```python
async def _read(session: AsyncSession, app_row: Application, user: User) -> InterviewKitRead:
    rows = await load_assignments(session, app_row.id)
    shown = visible_kits(
        await kits_in_round(session, app_row), rows,
        user=user, current_round=app_row.interview_round,
    )
    own = next(
        (r for r in rows_in_round(rows, app_row.interview_round) if r.user_id == user.id),
        None,
    )
    primary = next((k for k in shown if own is not None and k.track == own.track), None)
    if primary is None and shown:
        primary = shown[0]
    return InterviewKitRead(
        kit=content_of(primary) if primary else None,
        template_name=primary.template_name if primary else None,
        tracks=[
            TrackRead(track=k.track, template_id=k.template_id,
                      template_name=k.template_name, kit=content_of(k))
            for k in shown
        ],
        sheets=await _sheets_for(session, app_row, user),
    )
```

Add `visible_kits` to the `recruiter.pipeline.interview_sheets` import and `kits_in_round` to the `recruiter.pipeline.kit_store` import.

`src/recruiter/api/applications.py` — replace the `elif new_stage == Stage.INTERVIEWED:` branch body with:

```python
            # The recruiter closed the round by hand (a no-show, say).
            # Shares mark_interviewed with the automatic rule in
            # close_round_if_complete, so both stamp interviewed_at and
            # every track's closed_at the same way.
            mark_interviewed(app_row, await kits_in_round(session, app_row), now)
```

and add `kits_in_round` to its `recruiter.pipeline.kit_store` import.

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/unit/test_interview_sheets_rules.py tests/api/test_interview_tracks_read.py tests/api/test_interview_sheets_api.py tests/api/test_interview_submit.py tests/api/test_interview_rounds.py -q` (timeout 400000) — expected PASS.

- [ ] **Step 6: Whole suite, ruff, commit**

Run: `uv run pytest -q` (timeout 400000) — all pass. Ruff — 466.

```bash
git add src/recruiter tests/api/conftest.py tests/api/test_interview_tracks_read.py tests/unit/test_interview_sheets_rules.py
git commit -m "feat(interview-kit): read and close a round that has several tracks

The kit read lists every track the caller may see — all of them for a
recruiter, only their own for an interviewer — and keeps the one-track
kit field for existing clients. The blind rule is scoped to the track,
and closing a round, by hand or automatically, stamps every track.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Writing to one track — questions, sheets, generation

**Files:**
- Create: `src/recruiter/api/kit_tracks.py`
- Modify: `src/recruiter/api/interview.py`
- Test: `tests/unit/test_kit_tracks.py`, `tests/api/test_interview_tracks_write.py`

**Interfaces:**
- Consumes: `kits_in_round`, `rows_in_track`, `track_key` (Tasks 1–2).
- Produces:
  - `api/kit_tracks.py`: `resolve_track(kits, requested: str | None) -> InterviewKitRow` (404 no kit / unknown track, 422 several without `requested`); `own_row(rows, user) -> InterviewAssignment | None`; `kit_for_caller(kits, rows, user, requested) -> InterviewKitRow`.
  - `api/interview.py`: `NO_LLM_PROVIDER: str`; `run_generate_kit(*, application_id, engine, llm, bus, track: str = DEFAULT_TRACK)`; optional `?track=` on `POST …/interview-kit/generate`, `PATCH …/interview-kit`, `PATCH …/interview-kit/sheet`, `POST …/interview-kit/sheet/submit`, `POST …/interview-kit/draft-question`. Events from these endpoints carry `"track"`.

- [ ] **Step 1: Write the failing unit tests**

Create `tests/unit/test_kit_tracks.py`:

```python
import pytest
from fastapi import HTTPException

from recruiter.api.kit_tracks import kit_for_caller, own_row, resolve_track
from recruiter.models import InterviewAssignment, InterviewKitRow, Role, User


def _kit(track: str) -> InterviewKitRow:
    return InterviewKitRow(application_id=1, round=1, track=track, status="ready", questions=[])


def _user(uid: int, role: Role) -> User:
    u = User(email=f"u{uid}@acme.com", role=role, is_active=True)
    u.id = uid
    return u


def _row(uid: int, track: str) -> InterviewAssignment:
    return InterviewAssignment(application_id=1, user_id=uid, round=1, track=track, sheet={})


def _status(fn, *args) -> int:
    with pytest.raises(HTTPException) as exc:
        fn(*args)
    return exc.value.status_code


def test_resolve_track() -> None:
    one, two = [_kit("default")], [_kit("tech"), _kit("rh")]
    assert resolve_track(one, None) is one[0], "one track: ?track= may be left out"
    assert resolve_track(two, "rh") is two[1]
    assert _status(resolve_track, two, None) == 422, "several tracks: ?track= required"
    assert _status(resolve_track, two, "nope") == 404
    assert _status(resolve_track, [], None) == 404


def test_own_row() -> None:
    rows = [_row(1, "tech"), _row(2, "rh")]
    assert own_row(rows, _user(2, Role.VIEWER)) is rows[1]
    assert own_row(rows, _user(3, Role.VIEWER)) is None


def test_an_interviewer_works_on_their_own_track_only() -> None:
    kits, rows = [_kit("tech"), _kit("rh")], [_row(2, "rh")]
    viewer = _user(2, Role.VIEWER)
    assert kit_for_caller(kits, rows, viewer, None) is kits[1], "no ?track= needed"
    assert kit_for_caller(kits, rows, viewer, "rh") is kits[1]
    assert _status(kit_for_caller, kits, rows, viewer, "tech") == 403
    assert _status(kit_for_caller, kits, rows, _user(9, Role.VIEWER), None) == 403


def test_a_recruiter_names_the_track() -> None:
    kits = [_kit("tech"), _kit("rh")]
    recruiter = _user(5, Role.RECRUITER)
    assert kit_for_caller(kits, [], recruiter, "tech") is kits[0]
    assert _status(kit_for_caller, kits, [], recruiter, None) == 422
```

- [ ] **Step 2: Write the failing API tests**

Create `tests/api/test_interview_tracks_write.py`:

```python
"""Writing to one track of a two-track round (phase 3)."""
import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from recruiter.api.candidates import get_engine_dep, get_llm
from recruiter.api.interview import run_generate_kit
from recruiter.events import EventBus
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.models import InterviewAssignment, InterviewKitRow
from recruiter.schemas.interview import GeneratedQuestion, GeneratedQuestions

KIT = "/api/applications/{}/interview-kit"


def _q(qid: str, text: str) -> dict:
    return {"id": qid, "text": text, "source": "baseline"}


@pytest.fixture(autouse=True)
def _reset_limiter():
    from recruiter.api.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


def _db():
    return async_sessionmaker(app.dependency_overrides[get_engine_dep](), expire_on_commit=False)


async def _kit(app_id: int, track: str) -> InterviewKitRow | None:
    async with _db()() as s:
        return (await s.execute(select(InterviewKitRow).where(
            InterviewKitRow.application_id == app_id, InterviewKitRow.track == track,
        ))).scalar_one_or_none()


async def _row(app_id: int, user_id: int) -> InterviewAssignment:
    async with _db()() as s:
        return (await s.execute(select(InterviewAssignment).where(
            InterviewAssignment.application_id == app_id,
            InterviewAssignment.user_id == user_id,
        ))).scalar_one()


@pytest.mark.asyncio
async def test_a_recruiter_edits_one_named_track(api_client: AsyncClient, seed_tracks) -> None:
    app_id, _ = await seed_tracks()
    body = {"questions": [_q("r1", "rh question"), _q("r2", "Why us?")]}

    assert (await api_client.patch(KIT.format(app_id), json=body)).status_code == 422, (
        "two tracks: the recruiter must name one")
    r = await api_client.patch(f"{KIT.format(app_id)}?track=rh", json=body)

    assert r.status_code == 200, r.text
    assert [q["id"] for q in (await _kit(app_id, "rh")).questions] == ["r1", "r2"]
    assert [q["id"] for q in (await _kit(app_id, "tech")).questions] == ["q1"]


@pytest.mark.asyncio
async def test_an_interviewer_appends_to_their_own_track_only(
    api_client_unauth: AsyncClient, seed_tracks, login_as,
) -> None:
    app_id, _ = await seed_tracks()
    await login_as(api_client_unauth, "rh@acme.com")
    body = {"questions": [_q("r1", "rh question"), _q("r2", "Why us?")]}

    assert (await api_client_unauth.patch(KIT.format(app_id), json=body)).status_code == 200
    assert (await api_client_unauth.patch(
        f"{KIT.format(app_id)}?track=tech",
        json={"questions": [_q("q1", "tech question"), _q("q2", "More?")]},
    )).status_code == 403


@pytest.mark.asyncio
async def test_the_freeze_is_per_track(api_client: AsyncClient, seed_tracks) -> None:
    app_id, _ = await seed_tracks(submitted=("rh@acme.com",))

    assert (await api_client.patch(
        f"{KIT.format(app_id)}?track=tech", json={"questions": []},
    )).status_code == 200, "Technical has no submitted sheet: still editable"
    assert (await api_client.patch(
        f"{KIT.format(app_id)}?track=rh", json={"questions": []},
    )).status_code == 409, "RH is frozen by its submitted sheet"
    # generate depends on get_llm, which 503s without a provider before the
    # handler could answer 409 — give it one.
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()
    try:
        r = await api_client.post(f"{KIT.format(app_id)}/generate?track=rh")
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_generate_names_its_track(api_client: AsyncClient, seed_tracks) -> None:
    app_id, _ = await seed_tracks()
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient(structured_responses=[
        GeneratedQuestions(questions=[GeneratedQuestion(text="A probe.", criterion="x")]),
    ])
    try:
        assert (await api_client.post(f"{KIT.format(app_id)}/generate")).status_code == 422
        r = await api_client.post(f"{KIT.format(app_id)}/generate?track=tech")
    finally:
        app.dependency_overrides.pop(get_llm, None)

    assert r.status_code == 202, r.text
    assert "A probe." in [q["text"] for q in (await _kit(app_id, "tech")).questions]
    assert [q["id"] for q in (await _kit(app_id, "rh")).questions] == ["r1"]


@pytest.mark.asyncio
async def test_a_sheet_lands_on_the_callers_track(
    api_client_unauth: AsyncClient, seed_tracks, login_as,
) -> None:
    app_id, users = await seed_tracks()
    await login_as(api_client_unauth, "rh@acme.com")
    sheet = {"answers": {"r1": {"answer": "Loves it", "rating": "strong"},
                         "q1": {"answer": "not my track", "rating": None}},
             "verdict": {"decision": None, "note": None}}

    r = await api_client_unauth.patch(f"{KIT.format(app_id)}/sheet", json=sheet)
    assert r.status_code == 200, r.text
    saved = (await _row(app_id, users["rh@acme.com"])).sheet
    assert list(saved["answers"]) == ["r1"], "answers are pruned to the caller's track"

    assert (await api_client_unauth.patch(
        f"{KIT.format(app_id)}/sheet?track=tech", json=sheet,
    )).status_code == 409


@pytest.mark.asyncio
async def test_a_recruiter_can_take_an_unstaffed_track(
    api_client: AsyncClient, seed_tracks,
) -> None:
    app_id, _ = await seed_tracks(panel={"tech": ["tech@acme.com"]})
    sheet = {"answers": {}, "verdict": {"decision": None, "note": "fine"}}

    assert (await api_client.patch(f"{KIT.format(app_id)}/sheet", json=sheet)).status_code == 422
    r = await api_client.patch(f"{KIT.format(app_id)}/sheet?track=rh", json=sheet)
    assert r.status_code == 200, r.text
    tracks = sorted(s["track"] for s in r.json()["sheets"])
    assert tracks == ["rh", "tech"]


@pytest.mark.asyncio
async def test_generation_abandons_a_track_removed_meanwhile(
    api_client: AsyncClient, seed_tracks,
) -> None:
    app_id, _ = await seed_tracks()
    async with _db()() as s:
        await s.execute(update(InterviewKitRow).where(
            InterviewKitRow.application_id == app_id, InterviewKitRow.track == "tech",
        ).values(status="generating"))
        await s.commit()

    class _RemovesTrackMidCall:
        """Removes the track from another session while the model 'thinks',
        like a recruiter clicking Remove track mid-generation (same shape as
        test_interview_rounds.py's _BumpsRoundMidCall)."""

        async def chat_structured(self, *a: object, **kw: object) -> GeneratedQuestions:
            async with _db()() as other:
                await other.execute(delete(InterviewAssignment).where(
                    InterviewAssignment.application_id == app_id,
                    InterviewAssignment.track == "tech"))
                await other.execute(delete(InterviewKitRow).where(
                    InterviewKitRow.application_id == app_id, InterviewKitRow.track == "tech"))
                await other.commit()
            return GeneratedQuestions(questions=[GeneratedQuestion(text="Late.", criterion="x")])

    await run_generate_kit(
        application_id=app_id, track="tech", engine=app.dependency_overrides[get_engine_dep](),
        llm=_RemovesTrackMidCall(), bus=EventBus(),
    )

    assert await _kit(app_id, "tech") is None, "generation resurrected a removed track"
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_kit_tracks.py tests/api/test_interview_tracks_write.py -q` (timeout 400000)
Expected: FAIL — `recruiter.api.kit_tracks` missing; `?track=` ignored.

- [ ] **Step 4: Implement `api/kit_tracks.py`**

```python
"""Which track a kit request is about.

Recruiters and admins name a track with `?track=`; with one track in the
round it can be left out. An interviewer is on exactly one track per round,
so their track comes from their assignment and `?track=` may only repeat
it. Pure functions over already-loaded rows, so every router can share them
without importing each other.
"""
from fastapi import HTTPException

from recruiter.models import InterviewAssignment, InterviewKitRow, User
from recruiter.pipeline.interview_sheets import can_edit_questions


def resolve_track(kits: list[InterviewKitRow], requested: str | None) -> InterviewKitRow:
    """The kit `requested` names, or the round's only kit when it is None."""
    if not kits:
        raise HTTPException(status_code=404, detail="no interview kit; generate one first")
    if requested is not None:
        match = next((k for k in kits if k.track == requested), None)
        if match is None:
            raise HTTPException(status_code=404, detail=f"no track {requested!r} in this round")
        return match
    if len(kits) > 1:
        raise HTTPException(
            status_code=422, detail="this round has several tracks; name one with ?track=",
        )
    return kits[0]


def own_row(rows: list[InterviewAssignment], user: User) -> InterviewAssignment | None:
    """The caller's assignment among ONE round's rows."""
    return next((r for r in rows if r.user_id == user.id), None)


def kit_for_caller(
    kits: list[InterviewKitRow], rows: list[InterviewAssignment], user: User,
    requested: str | None,
) -> InterviewKitRow:
    """The kit a question edit or draft targets. Recruiters and admins:
    `resolve_track`. Anyone else must be on the round's panel (403) and
    works on their own track; naming another one is refused (403)."""
    if can_edit_questions(user):
        return resolve_track(kits, requested)
    own = own_row(rows, user)
    if own is None:
        raise HTTPException(status_code=403, detail="not assigned to this interview")
    if requested is not None and requested != own.track:
        raise HTTPException(status_code=403, detail="you are on another track")
    return resolve_track(kits, own.track)
```

- [ ] **Step 5: Make the interview endpoints track-aware**

In `src/recruiter/api/interview.py`:

1. Imports: add `from recruiter.api.kit_tracks import kit_for_caller, own_row, resolve_track`; add `rows_in_track` to the `interview_sheets` import; add `DEFAULT_TRACK`, `track_key` to the `kit_store` import.

2. After `logger = …`, add:

```python
# Shown on a kit that needs generated probes when no model is configured.
NO_LLM_PROVIDER = "No LLM provider configured. Set one up in Settings."
```

3. In `_read`, replace the inline `own = next(...)` with `own = own_row(rows_in_round(rows, app_row.interview_round), user)`.

4. `run_generate_kit` — signature becomes `*, application_id: int, engine: AsyncEngine, llm: LLMClient | None, bus: EventBus, track: str = DEFAULT_TRACK`. Then:
   - the dispatch-time read becomes `kit_row = await kit_for(session, app_row, track=track)` followed by `had_kit = kit_row is not None`;
   - `raise RuntimeError("No LLM provider configured. Set one up in Settings.")` becomes `raise RuntimeError(NO_LLM_PROVIDER)`;
   - after the lock, `kit_row = await kit_for(session, app_row)` becomes `kit_row = await kit_for(session, app_row, track=track)`; keep the round-moved abandon exactly as is, and after it insert:

```python
        if kit_row is None and had_kit:
            # The track was removed while the model was running (see
            # api/interview_tracks.remove_track). Recreating it here would
            # resurrect a track the recruiter just deleted.
            logger.warning(
                "interview kit generation abandoned: track %s was removed during "
                "generation for application %s", track, application_id,
            )
            return
        track_rows = rows_in_track(
            await load_assignments(session, application_id), app_row.interview_round, track,
        )
```

   - delete the old `rows = await load_assignments(session, application_id)` line, and replace both `rows_in_round(rows, app_row.interview_round)` expressions below it with `track_rows`;
   - the fallback `create_kit(session, app_row, round=app_row.interview_round)` gains `track=track`;
   - the published event gains `"track": track,`.

5. `generate_kit` — add the parameter `track: str | None = None` right after `background_tasks: BackgroundTasks,`, and replace everything from `kit_row = await kit_for(session, app_row)` down to (not including) the in-flight comment with:

```python
    kits = await kits_in_round(session, app_row)
    if kits:
        kit_row = resolve_track(kits, track)
    elif track is not None:
        raise HTTPException(status_code=404, detail=f"no track {track!r} in this round")
    else:
        kit_row = None
    existing_questions = kit_row.questions if kit_row else []
    frozen = kit_row is not None and is_frozen(rows_in_track(
        await load_assignments(session, application_id), app_row.interview_round,
        kit_row.track,
    ))
```

   Keep the freeze and in-flight blocks unchanged. Replace the `if kit_row is None: kit_row = await create_kit(...)` block with:

```python
    if kit_row is None:
        template = await job_default_template(session, app_row)
        kit_row = await create_kit(
            session, app_row, round=app_row.interview_round,
            track=track_key(template.id if template else None),
            **template_fields(template),
        )
```

   and pass `track=kit_row.track,` to `background_tasks.add_task(run_generate_kit, ...)`.

6. `patch_kit` — add `track: str | None = None` after `payload: InterviewKitPatch,`. Replace its body from `kit_row = await kit_for(session, app_row)` through the old interviewer 403 block with:

```python
    kits = await kits_in_round(session, app_row)
    if not kits:
        raise HTTPException(status_code=404, detail="no interview kit; generate one first")

    ids = [q.id for q in payload.questions]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="duplicate question ids")

    rows = rows_in_round(await load_assignments(session, application_id), app_row.interview_round)
    kit_row = kit_for_caller(kits, rows, user, track)
    kit = content_of(kit_row)
    # Freeze and recorded answers are this track's alone: a submitted RH
    # sheet must not lock the technical questions.
    track_rows = [r for r in rows if r.track == kit_row.track]
    stored_ids = [q.id for q in kit.questions]
    incoming_ids = [q.id for q in payload.questions]

    if not can_edit_questions(user):
        # An assigned interviewer may append to their own track, and
        # nothing else.
        prefix = payload.questions[:len(stored_ids)]
        unchanged = [q.model_dump(exclude={"added_by", "answer", "rating"}) for q in prefix] == [
            q.model_dump(exclude={"added_by", "answer", "rating"}) for q in kit.questions
        ]
        if not unchanged:
            raise HTTPException(status_code=403, detail="interviewers may only add questions")
```

   Then change `is_frozen(rows_in_round(rows, app_row.interview_round))` to `is_frozen(track_rows)`, and the `recorded = answered_question_ids(...)` generator to iterate `track_rows` (`r for r in track_rows if r.submitted_at is not None`). In the long comment above `recorded`, replace "Also scoped to the CURRENT round, like `is_frozen` above: each round owns its own kit and question ids now, so a question answered in an earlier, closed round cannot lock a same-id question in this one." with "Also scoped to this track of the CURRENT round, like `is_frozen` above: each track owns its own kit and question ids, so an answer on another track, or in an earlier round, cannot lock a same-id question here." Everything after is unchanged.

7. Replace `_own_assignment` with:

```python
async def _sheet_target(
    session: AsyncSession, app_row: Application, user: User, requested: str | None,
) -> tuple[InterviewKit, InterviewAssignment]:
    """The kit a sheet save or submit belongs to, and the caller's row.

    The caller's own assignment names the track; `?track=` may only repeat
    it (409 otherwise — their sheet is on another track). A recruiter or
    admin with no row gets one created on a track whose panel is empty —
    phase 1's zero-setup single-recruiter flow — naming the track with
    `?track=` when the round has several."""
    kits = await kits_in_round(session, app_row)
    rows = rows_in_round(
        await load_assignments(session, app_row.id), app_row.interview_round,
    )
    own = own_row(rows, user)
    if own is not None:
        if requested is not None and requested != own.track:
            raise HTTPException(status_code=409, detail="your sheet is on another track")
        return _require_kit(next((k for k in kits if k.track == own.track), None)), own
    kit_row = resolve_track(kits, requested)
    if can_edit_questions(user) and not any(r.track == kit_row.track for r in rows):
        own = InterviewAssignment(
            application_id=app_row.id, user_id=user.id,
            round=app_row.interview_round, track=kit_row.track,
        )
        session.add(own)
        await session.flush()
        return content_of(kit_row), own
    raise HTTPException(status_code=404, detail="you are not assigned to this interview")
```

8. `patch_sheet` — add `track: str | None = None` after `payload: InterviewSheet,`; replace the two lines `kit = _require_kit(await kit_for(session, app_row))` and `own = await _own_assignment(session, app_row, user)` with `kit, own = await _sheet_target(session, app_row, user, track)`.

9. `submit_sheet` — add `track: str | None = None` after `application_id: int,`; the same two-line replacement; the published event gains `"track": own.track,`.

10. `draft_kit_question` — add `track: str | None = None` after `payload: DraftQuestionRequest,`. Replace the block from `if not can_edit_questions(user):` (the 403) through the `existing = [...]` list with:

```python
    rows = rows_in_round(
        await load_assignments(session, application_id), app_row.interview_round,
    )
    if not can_edit_questions(user) and own_row(rows, user) is None:
        raise HTTPException(status_code=403, detail="not assigned to this interview")

    if llm is None:
        raise HTTPException(
            status_code=503,
            detail="No LLM provider configured — set one in Settings → LLM.",
        )

    job = await session.get(Job, app_row.job_id)
    candidate = await session.get(Candidate, app_row.candidate_id)
    kits = await kits_in_round(session, app_row)
    kit_row = kit_for_caller(kits, rows, user, track) if kits else None
    existing = [
        q.get("text", "")
        for q in (kit_row.questions if kit_row else [])
        if q.get("text")
    ]
```

Remove imports that are no longer used (ruff F401 will name them).

- [ ] **Step 6: Run to verify they pass**

Run: `uv run pytest tests/unit/test_kit_tracks.py tests/api/test_interview_tracks_write.py tests/api/test_interview_api.py tests/api/test_interview_sheets_api.py tests/api/test_interview_freeze_api.py tests/api/test_interview_stage_wiring.py tests/api/test_interview_rounds.py tests/api/test_viewer_interviewer_exception.py -q` (timeout 400000) — expected PASS.

- [ ] **Step 7: Whole suite, ruff, commit**

Run: `uv run pytest -q` (timeout 400000); ruff — 466.

```bash
git add src/recruiter/api tests/unit/test_kit_tracks.py tests/api/test_interview_tracks_write.py
git commit -m "feat(interview-kit): questions, sheets and generation act on one track

Recruiters name a track with ?track= (optional when the round has one);
an interviewer's own assignment names theirs. Freezing and answered-
question protection are per track, and a generation whose track was
removed while the model ran abandons instead of recreating it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: One panel per track

**Files:**
- Modify: `src/recruiter/api/kit_tracks.py`, `src/recruiter/api/interviewers.py`
- Test: `tests/unit/test_kit_tracks.py`, `tests/api/test_interview_tracks_panel.py`

**Interfaces:**
- Consumes: `resolve_track`, `kits_in_round`, `rows_in_round`, `close_round_if_complete`.
- Produces: `target_track(kits, requested: str | None) -> str`; `InterviewerRead.track: str`; `PUT /api/applications/{id}/interviewers?track=…`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_kit_tracks.py` (add `target_track` to the import):

```python
def test_a_panel_picked_before_any_kit_goes_on_default() -> None:
    assert target_track([], None) == "default"
    assert target_track([], "default") == "default"
    assert _status(target_track, [], "rh") == 404
    assert target_track([_kit("tech"), _kit("rh")], "rh") == "rh"
    assert _status(target_track, [_kit("tech"), _kit("rh")], None) == 422
```

Create `tests/api/test_interview_tracks_panel.py`:

```python
"""Each track has its own panel (phase 3)."""
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from recruiter.api.candidates import get_engine_dep
from recruiter.auth.passwords import hash_password
from recruiter.main import app
from recruiter.models import InterviewAssignment, Role, User

PANEL = "/api/applications/{}/interviewers"


def _db():
    return async_sessionmaker(app.dependency_overrides[get_engine_dep](), expire_on_commit=False)


async def _user(email: str) -> int:
    async with _db()() as s:
        u = User(email=email, role=Role.VIEWER, is_active=True, password_hash=hash_password("x"))
        s.add(u)
        await s.commit()
        return u.id


async def _panel(app_id: int) -> list[tuple[int, str]]:
    async with _db()() as s:
        rows = (await s.execute(select(InterviewAssignment).where(
            InterviewAssignment.application_id == app_id,
        ).order_by(InterviewAssignment.id))).scalars().all()
        return [(r.user_id, r.track) for r in rows]


@pytest.mark.asyncio
async def test_the_panel_lists_each_interviewers_track(
    api_client: AsyncClient, seed_tracks,
) -> None:
    app_id, users = await seed_tracks()
    rows = (await api_client.get(PANEL.format(app_id))).json()
    assert {(r["user_id"], r["track"]) for r in rows} == {
        (users["tech@acme.com"], "tech"), (users["rh@acme.com"], "rh")}


@pytest.mark.asyncio
async def test_setting_one_tracks_panel_leaves_the_other_alone(
    api_client: AsyncClient, seed_tracks,
) -> None:
    app_id, users = await seed_tracks()
    carol = await _user("carol@acme.com")

    r = await api_client.put(f"{PANEL.format(app_id)}?track=rh",
                             json={"user_ids": [users["rh@acme.com"], carol]})

    assert r.status_code == 200, r.text
    assert sorted(await _panel(app_id)) == sorted([
        (users["tech@acme.com"], "tech"), (users["rh@acme.com"], "rh"), (carol, "rh")])


@pytest.mark.asyncio
async def test_a_person_cannot_join_a_second_track(api_client: AsyncClient, seed_tracks) -> None:
    app_id, users = await seed_tracks()
    r = await api_client.put(f"{PANEL.format(app_id)}?track=rh",
                             json={"user_ids": [users["tech@acme.com"]]})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_two_tracks_need_a_named_track(api_client: AsyncClient, seed_tracks) -> None:
    app_id, users = await seed_tracks()
    r = await api_client.put(PANEL.format(app_id), json={"user_ids": []})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_a_panel_picked_before_scheduling_goes_on_default(
    api_client: AsyncClient, create_scored_app,
) -> None:
    app_id = await create_scored_app()
    carol = await _user("carol@acme.com")
    r = await api_client.put(PANEL.format(app_id), json={"user_ids": [carol]})
    assert r.status_code == 200, r.text
    assert await _panel(app_id) == [(carol, "default")]


@pytest.mark.asyncio
async def test_removing_the_last_unsubmitted_sheet_closes_a_staffed_round(
    api_client: AsyncClient, seed_tracks,
) -> None:
    app_id, users = await seed_tracks(
        panel={"tech": ["tech@acme.com"], "rh": ["rh@acme.com", "rh2@acme.com"]},
        submitted=("tech@acme.com", "rh@acme.com"),
    )
    r = await api_client.put(f"{PANEL.format(app_id)}?track=rh",
                             json={"user_ids": [users["rh@acme.com"]]})
    assert r.status_code == 200, r.text
    stage = (await api_client.get(f"/api/applications/{app_id}")).json()["stage"]
    assert stage == "interviewed"


@pytest.mark.asyncio
async def test_emptying_a_track_does_not_close_the_round(
    api_client: AsyncClient, seed_tracks,
) -> None:
    app_id, _ = await seed_tracks(submitted=("tech@acme.com",))
    r = await api_client.put(f"{PANEL.format(app_id)}?track=rh", json={"user_ids": []})
    assert r.status_code == 200, r.text
    stage = (await api_client.get(f"/api/applications/{app_id}")).json()["stage"]
    assert stage == "scheduled", "an unstaffed track keeps the round open"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_kit_tracks.py tests/api/test_interview_tracks_panel.py -q` (timeout 400000) — expected FAIL (`target_track` missing; `track` absent; `?track=` ignored).

- [ ] **Step 3: Implement**

Append to `src/recruiter/api/kit_tracks.py` (add `from recruiter.pipeline.kit_store import DEFAULT_TRACK` to its imports):

```python
def target_track(kits: list[InterviewKitRow], requested: str | None) -> str:
    """The track a panel edit targets. Before the round has any kit — a
    panel picked ahead of scheduling — that is `default`; the round's
    tracks adopt those rows when they are created (see
    round_tracks.adopt_orphan_rows). Once kits exist, `resolve_track`."""
    if not kits:
        if requested not in (None, DEFAULT_TRACK):
            raise HTTPException(status_code=404, detail=f"no track {requested!r} in this round")
        return DEFAULT_TRACK
    return resolve_track(kits, requested).track
```

In `src/recruiter/api/interviewers.py`:

1. Imports: `from recruiter.api.kit_tracks import target_track` and `from recruiter.pipeline.kit_store import kits_in_round`.
2. `InterviewerRead` gains, after `submitted_at`:

```python
    # Which track of the live round they are on — one per person per round.
    track: str
```

3. In `_read_all`, add `track=r.track,` to the `InterviewerRead(...)` call, and change its docstring's first sentence to "The panel for the round in progress, every track."
4. In `put_interviewers`, add the parameter `track: str | None = None,` after `payload: InterviewersPut,`; extend the docstring with "`?track=` names the track whose panel this is (optional when the round has one track, or none yet); a person already on another track of this round is refused (409)." Replace the lines from `wanted = list(dict.fromkeys(payload.user_ids))` through `by_user = {r.user_id: r for r in existing}` with:

```python
    target = target_track(await kits_in_round(session, app_row), track)
    round_rows = rows_in_round(
        await load_assignments(session, application_id), app_row.interview_round,
    )
    existing = [r for r in round_rows if r.track == target]
    by_user = {r.user_id: r for r in existing}
    wanted = list(dict.fromkeys(payload.user_ids))  # dedupe, keep order
    # One track per person per round: moving someone means taking them off
    # their current track first.
    clash = sorted(r.user_id for r in round_rows if r.track != target and r.user_id in wanted)
    if clash:
        raise HTTPException(
            status_code=409, detail=f"already on another track this round: {clash}",
        )
```

   New rows are created with `track=target` (add it to the `InterviewAssignment(...)` call). The published event gains `"track": target,`.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_kit_tracks.py tests/api/test_interview_tracks_panel.py tests/api/test_interviewers_api.py -q` (timeout 400000) — expected PASS.

- [ ] **Step 5: Whole suite, ruff, commit**

Run: `uv run pytest -q` (timeout 400000); ruff — 466.

```bash
git add src/recruiter/api tests/unit/test_kit_tracks.py tests/api/test_interview_tracks_panel.py
git commit -m "feat(interview-kit): each track has its own panel

The panel endpoint reports each interviewer's track and edits one
track's panel at a time; someone already on another track of the round
is refused. A panel picked before the round has any kit still goes on
the default track, as before.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Starting, rescheduling and reopening a round with several tracks

**Files:**
- Create: `src/recruiter/api/round_tracks.py`
- Modify: `src/recruiter/schemas/application.py`, `src/recruiter/api/interview.py`, `src/recruiter/api/applications.py`
- Test: `tests/api/test_interview_track_rounds.py`

**Interfaces:**
- Consumes: `track_key`, `kits_in_round`, `create_kit`, `template_fields`, `is_frozen`, `sheet_has_content`, `run_generate_kit(track=…)`, `NO_LLM_PROVIDER`.
- Produces:
  - `ApplicationUpdate.interview_template_ids: list[int | None] | None`
  - `round_tracks.create_track(session, app_row, template, now) -> InterviewKitRow`
  - `round_tracks.adopt_orphan_rows(session, app_row) -> None`
  - `round_tracks.start_round(session, app_row, choices, now) -> list[str]` (tracks to generate)
  - `round_tracks.open_next_round(session, app_row, choices, now) -> list[str]`
  - `interview.dispatch_generation(session, background_tasks, app_row, tracks, *, engine, llm, bus) -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_interview_track_rounds.py`:

```python
"""Starting, rescheduling and reopening a round with several tracks."""
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from recruiter.api.candidates import get_engine_dep, get_llm
from recruiter.api.interview import NO_LLM_PROVIDER
from recruiter.auth.passwords import hash_password
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.models import (
    Application, InterviewAssignment, InterviewKitRow, InterviewTemplate, Role, Stage, User,
)
from recruiter.schemas.interview import GeneratedQuestion, GeneratedQuestions


def _llm() -> FakeLLMClient:
    return FakeLLMClient(structured_responses=[GeneratedQuestions(questions=[
        GeneratedQuestion(text="A generated probe.", criterion="x"),
    ])])


def _db():
    return async_sessionmaker(app.dependency_overrides[get_engine_dep](), expire_on_commit=False)


async def _template(name: str, *, probe_mode: str = "none", include: bool = False,
                    active: bool = True) -> int:
    async with _db()() as s:
        t = InterviewTemplate(name=name, questions=[{"id": "m1", "text": f"{name}?"}],
                              probe_mode=probe_mode, include_job_questions=include,
                              is_active=active)
        s.add(t)
        await s.commit()
        return t.id


async def _invited(api_client: AsyncClient, create_scored_app) -> int:
    app_id = await create_scored_app()
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
    async with _db()() as s:
        await s.execute(update(Application).where(Application.id == app_id)
                        .values(stage=Stage.INVITED))
        await s.commit()
    return app_id


async def _schedule(api_client: AsyncClient, app_id: int, llm=None, **extra):
    if llm is not None:
        app.dependency_overrides[get_llm] = lambda: llm
    try:
        return await api_client.patch(f"/api/applications/{app_id}",
                                      json={"stage": "scheduled", **extra})
    finally:
        app.dependency_overrides.pop(get_llm, None)


async def _kits(app_id: int) -> list[InterviewKitRow]:
    async with _db()() as s:
        return list((await s.execute(select(InterviewKitRow)
                     .where(InterviewKitRow.application_id == app_id)
                     .order_by(InterviewKitRow.round, InterviewKitRow.id))).scalars().all())


async def _add_panel(app_id: int, *, track: str, email: str, round_number: int = 1,
                     sheet: dict | None = None) -> int:
    async with _db()() as s:
        u = User(email=email, role=Role.VIEWER, is_active=True, password_hash=hash_password("x"))
        s.add(u)
        await s.flush()
        row = InterviewAssignment(application_id=app_id, user_id=u.id, round=round_number,
                                  track=track)
        if sheet is not None:
            row.sheet = sheet
        s.add(row)
        await s.commit()
        return u.id


async def _panel(app_id: int, round_number: int) -> list[tuple[int, str]]:
    async with _db()() as s:
        rows = (await s.execute(select(InterviewAssignment).where(
            InterviewAssignment.application_id == app_id,
            InterviewAssignment.round == round_number,
        ).order_by(InterviewAssignment.id))).scalars().all()
        return [(r.user_id, r.track) for r in rows]


async def _reject_and_reinvite(api_client: AsyncClient, app_id: int) -> None:
    """Back to INVITED in the SAME round: reject, unreject, validate, then
    set INVITED in the DB (the API has no "invited" stage literal)."""
    for stage in ("rejected", "scored", "validated"):
        r = await api_client.patch(f"/api/applications/{app_id}", json={"stage": stage})
        assert r.status_code == 200, r.text
    async with _db()() as s:
        await s.execute(update(Application).where(Application.id == app_id)
                        .values(stage=Stage.INVITED))
        await s.commit()


@pytest.mark.asyncio
async def test_scheduling_two_templates_makes_two_tracks(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tech = await _template("Technical", probe_mode="score_gaps", include=True)
    rh = await _template("RH screen")
    app_id = await _invited(api_client, create_scored_app)
    llm = _llm()

    r = await _schedule(api_client, app_id, llm, interview_template_ids=[tech, rh])

    assert r.status_code == 200, r.text
    kits = await _kits(app_id)
    assert [k.track for k in kits] == [f"t{tech}", f"t{rh}"]
    assert [k.status for k in kits] == ["ready", "ready"]
    assert len(llm.calls) == 1, "only the score-gap track calls the model"


@pytest.mark.asyncio
async def test_track_choices_are_validated(api_client: AsyncClient, create_scored_app) -> None:
    rh = await _template("RH screen")
    old = await _template("Old", active=False)
    app_id = await _invited(api_client, create_scored_app)

    for body in ({"interview_template_ids": [rh], "interview_template_id": rh},
                 {"interview_template_ids": []},
                 {"interview_template_ids": [old]}):
        assert (await _schedule(api_client, app_id, _llm(), **body)).status_code == 422, body

    other = await create_scored_app()
    r = await api_client.patch(f"/api/applications/{other}",
                               json={"stage": "validated", "interview_template_ids": [rh]})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_duplicate_choices_make_one_track_each(
    api_client: AsyncClient, create_scored_app,
) -> None:
    rh = await _template("RH screen")
    app_id = await _invited(api_client, create_scored_app)

    r = await _schedule(api_client, app_id, _llm(), interview_template_ids=[rh, rh, None, None])

    assert r.status_code == 200, r.text
    assert [k.track for k in await _kits(app_id)] == [f"t{rh}", "default"]


@pytest.mark.asyncio
async def test_without_a_provider_only_the_track_that_needs_one_fails(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tech = await _template("Technical", probe_mode="score_gaps", include=True)
    rh = await _template("RH screen")
    app_id = await _invited(api_client, create_scored_app)

    r = await _schedule(api_client, app_id, interview_template_ids=[tech, rh])

    assert r.status_code == 200, r.text
    by_track = {k.track: k for k in await _kits(app_id)}
    assert (by_track[f"t{tech}"].status, by_track[f"t{tech}"].error) == ("error", NO_LLM_PROVIDER)
    assert by_track[f"t{rh}"].status == "ready"


@pytest.mark.asyncio
async def test_scheduling_the_same_round_again_reconciles_its_tracks(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tech = await _template("Technical")
    rh = await _template("RH screen")
    culture = await _template("Culture")
    app_id = await _invited(api_client, create_scored_app)
    await _schedule(api_client, app_id, interview_template_ids=[tech, rh])
    await _add_panel(app_id, track=f"t{tech}", email="alice@acme.com")
    await _add_panel(app_id, track=f"t{rh}", email="carol@acme.com",
                     sheet={"answers": {}, "verdict": {"decision": None, "note": "promising"}})
    await _reject_and_reinvite(api_client, app_id)

    r = await _schedule(api_client, app_id, interview_template_ids=[culture])

    assert r.status_code == 200, r.text
    assert [k.track for k in await _kits(app_id)] == [f"t{rh}", f"t{culture}"], (
        "Technical was unticked and empty: removed with its panel; RH has a draft: kept")
    assert [t for _, t in await _panel(app_id, 1)] == [f"t{rh}"]


@pytest.mark.asyncio
async def test_another_round_copies_chosen_tracks_and_starts_new_ones(
    api_client: AsyncClient, create_scored_app,
) -> None:
    tech = await _template("Technical")
    rh = await _template("RH screen")
    culture = await _template("Culture")
    app_id = await _invited(api_client, create_scored_app)
    await _schedule(api_client, app_id, interview_template_ids=[tech, rh])
    alice = await _add_panel(app_id, track=f"t{tech}", email="alice@acme.com")
    await _add_panel(app_id, track=f"t{rh}", email="carol@acme.com")
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "interviewed"})

    r = await _schedule(api_client, app_id, interview_template_ids=[tech, culture])

    assert r.status_code == 200, r.text
    kits = await _kits(app_id)
    round_one = {k.track: k for k in kits if k.round == 1}
    round_two = [k for k in kits if k.round == 2]
    assert [k.track for k in round_two] == [f"t{tech}", f"t{culture}"]
    assert round_two[0].questions == round_one[f"t{tech}"].questions
    assert round_two[0].template_snapshot == round_one[f"t{tech}"].template_snapshot
    assert await _panel(app_id, 2) == [(alice, f"t{tech}")], (
        "only a copied track brings its panel; RH stays in round one")


@pytest.mark.asyncio
async def test_interviewers_picked_before_scheduling_join_the_first_track(
    api_client: AsyncClient, create_scored_app,
) -> None:
    rh = await _template("RH screen")
    app_id = await _invited(api_client, create_scored_app)
    early = await _add_panel(app_id, track="default", email="early@acme.com")

    await _schedule(api_client, app_id, interview_template_ids=[rh])

    assert await _panel(app_id, 1) == [(early, f"t{rh}")]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/api/test_interview_track_rounds.py -q` (timeout 400000) — expected FAIL (`interview_template_ids` unknown/ignored; `NO_LLM_PROVIDER` import works from Task 3).

- [ ] **Step 3: The payload field**

In `src/recruiter/schemas/application.py`, add after `interview_template_id`:

```python
    # The tracks of the round being started (phase 3): the ticked templates,
    # `null` being the no-template track. `interview_template_id` is phase
    # 2's shorthand for a one-item list; sending both is a 422.
    interview_template_ids: list[int | None] | None = None
```

- [ ] **Step 4: `api/round_tracks.py`**

```python
"""A round's tracks: made when a round starts, reconciled when the same
round is scheduled again, carried into the next round.

Design: docs/superpowers/specs/2026-09-22-interview-tracks-design.md. Every
function here runs inside `patch_application` (or the tracks router) under
the application row lock its caller took. Those that start tracks return
the keys whose generation must be dispatched after the commit (see
api/interview.dispatch_generation).
"""
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.interviewers import load_assignments
from recruiter.models import Application, InterviewAssignment, InterviewKitRow, InterviewTemplate
from recruiter.models.interview_assignment import empty_sheet
from recruiter.pipeline.interview_sheets import is_frozen, rows_in_round, sheet_has_content
from recruiter.pipeline.kit_store import create_kit, kits_in_round, template_fields, track_key


def _key(template: InterviewTemplate | None) -> str:
    return track_key(template.id if template is not None else None)


async def create_track(
    session: AsyncSession, app_row: Application, template: InterviewTemplate | None,
    now: datetime,
) -> InterviewKitRow:
    """A new track in the live round: its kit, pending generation."""
    kit = await create_kit(
        session, app_row, round=app_row.interview_round, track=_key(template),
        status="generating", **template_fields(template),
    )
    # Pairs with generate_kit's in-flight check, so a manual Generate
    # during this run is a no-op rather than a second model call.
    kit.generating_since = now.isoformat()
    return kit


async def adopt_orphan_rows(session: AsyncSession, app_row: Application) -> None:
    """Interviewers picked before the round had a kit sit on `default`. Once
    the round's tracks exist, any live-round row on a track with no kit
    joins the round's first track, so nobody picked early is stranded."""
    kits = await kits_in_round(session, app_row)
    if not kits:
        return
    tracks = {k.track for k in kits}
    for row in rows_in_round(
        await load_assignments(session, app_row.id), app_row.interview_round,
    ):
        if row.track not in tracks:
            row.track = kits[0].track


async def start_round(
    session: AsyncSession, app_row: Application,
    choices: list[InterviewTemplate | None], now: datetime,
) -> list[str]:
    """Scheduling the live round, first time or again (reject → re-invite →
    schedule keeps the round number).

    Each chosen template's track: absent → created; frozen with questions →
    left as it is, a stuck `error`/`generating` kit recovered to `ready`
    (regenerating would orphan submitted answers); otherwise regenerated,
    which keeps answered questions (run_generate_kit). Tracks not chosen are
    removed with their panel rows when nobody on them has written anything,
    and kept otherwise.
    """
    rows = rows_in_round(
        await load_assignments(session, app_row.id), app_row.interview_round,
    )
    existing = {k.track: k for k in await kits_in_round(session, app_row)}
    wanted = {_key(t) for t in choices}
    to_generate: list[str] = []
    for template in choices:
        key = _key(template)
        kit = existing.get(key)
        if kit is None:
            await create_track(session, app_row, template, now)
            to_generate.append(key)
            continue
        if is_frozen(r for r in rows if r.track == key) and kit.questions:
            if kit.status != "ready":
                kit.status = "ready"
                kit.error = None
            continue
        kit.status = "generating"
        kit.error = None
        kit.generating_since = now.isoformat()
        to_generate.append(key)
    for key, kit in existing.items():
        if key in wanted:
            continue
        panel = [r for r in rows if r.track == key]
        if any(r.submitted_at is not None or sheet_has_content(r.sheet) for r in panel):
            continue
        for row in panel:
            await session.delete(row)
        await session.delete(kit)
    await session.flush()
    await adopt_orphan_rows(session, app_row)
    return to_generate


async def open_next_round(
    session: AsyncSession, app_row: Application,
    choices: list[InterviewTemplate | None], now: datetime,
) -> list[str]:
    """Reopen an interviewed application for another round, one track per
    choice.

    A choice the closing round also used (matched by template, no template
    matching no template) copies that track forward: questions, snapshot,
    status and error, plus its panel on empty sheets. Any other choice
    starts a fresh track, generated, with no panel. Tracks of the closing
    round that were not chosen stay in its history.
    """
    previous_round = app_row.interview_round
    previous_rows = rows_in_round(await load_assignments(session, app_row.id), previous_round)
    previous = {k.template_id: k for k in await kits_in_round(session, app_row)}

    app_row.interview_round = previous_round + 1
    # The round is open again, so the application is no longer interviewed.
    app_row.interviewed_at = None

    if not previous and choices == [None]:
        # A round that never had a kit, reopened with no template: as before
        # tracks, the panel carries over and no kit is made.
        for row in previous_rows:
            session.add(InterviewAssignment(
                application_id=app_row.id, user_id=row.user_id,
                round=app_row.interview_round, track=row.track, sheet=empty_sheet(),
            ))
        return []

    to_generate: list[str] = []
    for template in choices:
        before = previous.get(template.id if template is not None else None)
        if before is None:
            await create_track(session, app_row, template, now)
            to_generate.append(_key(template))
            continue
        # Carry the previous kit's status and error forward rather than
        # forcing "ready": a round stuck in "error" must stay visibly broken
        # on reopen too, or the recruiter sees an empty ready kit with the
        # failure hidden instead of a reason to regenerate it.
        await create_kit(
            session, app_row, round=app_row.interview_round, track=before.track,
            questions=list(before.questions or []),
            status=before.status, error=before.error,
            template_id=before.template_id, template_name=before.template_name,
            template_snapshot=before.template_snapshot,
        )
        for row in previous_rows:
            if row.track == before.track:
                session.add(InterviewAssignment(
                    application_id=app_row.id, user_id=row.user_id,
                    round=app_row.interview_round, track=before.track, sheet=empty_sheet(),
                ))
    return to_generate
```

- [ ] **Step 5: `dispatch_generation`**

In `src/recruiter/api/interview.py`, after `run_generate_kit`:

```python
async def dispatch_generation(
    session: AsyncSession, background_tasks: BackgroundTasks, app_row: Application,
    tracks: list[str], *, engine: AsyncEngine, llm: LLMClient | None, bus: EventBus,
) -> None:
    """Enqueue one generation per track, after the commit that marked each
    track's kit `generating` — the stage transition must be durable before
    anything that can fail runs.

    A track whose snapshot wants no probes runs without a model. One that
    needs a model when none is configured is failed on its own — the other
    tracks still generate — rather than left stuck at `generating` with no
    task ever coming to resolve it.
    """
    failed = False
    for track in tracks:
        kit_row = await kit_for(session, app_row, track=track)
        if kit_row is None:
            continue
        if llm is not None or not wants_probes(snapshot_from_row(kit_row)):
            background_tasks.add_task(
                run_generate_kit, application_id=app_row.id, track=track,
                engine=engine, llm=llm, bus=bus,
            )
        else:
            kit_row.status = "error"
            kit_row.error = NO_LLM_PROVIDER
            failed = True
    if failed:
        await session.commit()
```

- [ ] **Step 6: Wire `patch_application`**

In `src/recruiter/api/applications.py`:

1. Replace `_resolve_round_template` with:

```python
async def _resolve_round_choices(
    session: AsyncSession, app_row: Application, payload: ApplicationUpdate,
) -> list[InterviewTemplate | None]:
    """The templates the round being started runs, one track each, `None`
    being the no-template track. `interview_template_ids` lists them;
    `interview_template_id` is phase 2's shorthand for one; neither → the
    job's default, or no template when it has none. Duplicates collapse."""
    if "interview_template_ids" in payload.model_fields_set:
        if not payload.interview_template_ids:
            raise HTTPException(status_code=422, detail="choose at least one track")
        wanted = list(dict.fromkeys(payload.interview_template_ids))
    elif "interview_template_id" in payload.model_fields_set:
        wanted = [payload.interview_template_id]
    else:
        return [await job_default_template(session, app_row)]
    choices: list[InterviewTemplate | None] = []
    for template_id in wanted:
        if template_id is None:
            choices.append(None)
            continue
        template = await session.get(InterviewTemplate, template_id)
        if template is None or not template.is_active:
            raise HTTPException(status_code=422, detail="unknown or archived interview template")
        choices.append(template)
    return choices
```

2. Delete `_open_next_round`.

3. In `patch_application`, replace the `if "interview_template_id" in payload.model_fields_set and payload.stage != "scheduled":` check with:

```python
    sent = {"interview_template_id", "interview_template_ids"} & payload.model_fields_set
    if sent and payload.stage != "scheduled":
        raise HTTPException(
            status_code=422,
            detail="interview templates are only meaningful when scheduling a round",
        )
    if len(sent) == 2:
        raise HTTPException(
            status_code=422,
            detail="send interview_template_ids or interview_template_id, not both",
        )
```

   Replace `schedule_kit_generation = False` with `tracks_to_generate: list[str] = []`. Replace the `round_template = (...)` assignment with:

```python
        choices = (
            await _resolve_round_choices(session, app_row, payload)
            if new_stage == Stage.SCHEDULED else []
        )
```

   Replace both SCHEDULED branches with:

```python
        elif new_stage == Stage.SCHEDULED and previous_stage == Stage.INTERVIEWED:
            app_row.scheduled_at = now
            tracks_to_generate = await open_next_round(session, app_row, choices, now)
        elif new_stage == Stage.SCHEDULED:
            app_row.scheduled_at = now
            # Marks each chosen track pending here; the model calls are
            # enqueued AFTER the commit below. The transition must be
            # durable before anything that can fail runs — a stuck stage is
            # far worse than a missing kit.
            tracks_to_generate = await start_round(session, app_row, choices, now)
```

   Replace the whole `if schedule_kit_generation:` block after the commit/refreshes with:

```python
    if tracks_to_generate:
        await dispatch_generation(
            session, background_tasks, app_row, tracks_to_generate,
            engine=engine, llm=llm, bus=bus,
        )
        await session.refresh(app_row)
```

4. Imports: add `from recruiter.api.round_tracks import open_next_round, start_round`; import `dispatch_generation` (instead of `run_generate_kit`) from `recruiter.api.interview`; drop what ruff reports unused (`create_kit`, `kit_for`, `template_fields`, `snapshot_from_row`, `wants_probes`, `is_frozen`, `empty_sheet`, possibly `InterviewAssignment`).

- [ ] **Step 7: Run to verify they pass**

Run: `uv run pytest tests/api/test_interview_track_rounds.py tests/api/test_interview_template_rounds.py tests/api/test_interview_rounds.py tests/api/test_interview_stage_wiring.py -q` (timeout 400000) — expected PASS, including every phase-1 and phase-2 rounds test unchanged.

- [ ] **Step 8: Whole suite, ruff, commit**

Run: `uv run pytest -q` (timeout 400000); ruff — 466.

```bash
git add src/recruiter tests/api/test_interview_track_rounds.py
git commit -m "feat(interview-kit): start and reopen rounds with several tracks

Scheduling takes interview_template_ids and makes one track per choice,
each generated on its own; a track that needs a model fails alone when
none is configured. Scheduling the same round again reconciles its
tracks, and another round copies the chosen tracks forward with their
panels. Interviewers picked before scheduling join the first track.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Adding and removing a track mid-round

**Files:**
- Create: `src/recruiter/api/interview_tracks.py`
- Modify: `src/recruiter/main.py`
- Test: `tests/api/test_interview_tracks_api.py`

**Interfaces:**
- Consumes: `create_track`, `dispatch_generation`, `_read`, `kits_in_round`, `kit_for`, `track_key`, `rows_in_track`, `sheet_has_content`, `close_round_if_complete`.
- Produces: `POST /api/applications/{id}/interview-tracks` `{template_id: int | null}` → 201 `InterviewKitRead`; `DELETE /api/applications/{id}/interview-tracks/{track}` → 200 `InterviewKitRead`.

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_interview_tracks_api.py`:

```python
"""Adding and removing a track while the interview is scheduled."""
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from recruiter.api.candidates import get_engine_dep, get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.models import Application, InterviewAssignment, InterviewTemplate, Stage
from recruiter.schemas.interview import GeneratedQuestion, GeneratedQuestions

TRACKS = "/api/applications/{}/interview-tracks"


def _db():
    return async_sessionmaker(app.dependency_overrides[get_engine_dep](), expire_on_commit=False)


async def _template(name: str, *, active: bool = True) -> int:
    async with _db()() as s:
        t = InterviewTemplate(name=name, questions=[{"id": "m1", "text": f"{name}?"}],
                              probe_mode="none", include_job_questions=False, is_active=active)
        s.add(t)
        await s.commit()
        return t.id


async def _scheduled(api_client: AsyncClient, create_scored_app) -> int:
    """An application scheduled with one default track."""
    app_id = await create_scored_app()
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
    async with _db()() as s:
        await s.execute(update(Application).where(Application.id == app_id)
                        .values(stage=Stage.INVITED))
        await s.commit()
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient(structured_responses=[
        GeneratedQuestions(questions=[GeneratedQuestion(text="A probe.", criterion="x")]),
    ])
    try:
        r = await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert r.status_code == 200, r.text
    return app_id


async def _write_draft(app_id: int, user_id: int) -> None:
    async with _db()() as s:
        await s.execute(update(InterviewAssignment).where(
            InterviewAssignment.application_id == app_id,
            InterviewAssignment.user_id == user_id,
        ).values(sheet={"answers": {}, "verdict": {"decision": None, "note": "promising"}}))
        await s.commit()


@pytest.mark.asyncio
async def test_adding_a_track_creates_and_generates_it(
    api_client: AsyncClient, create_scored_app,
) -> None:
    rh = await _template("RH screen")
    app_id = await _scheduled(api_client, create_scored_app)

    r = await api_client.post(TRACKS.format(app_id), json={"template_id": rh})

    assert r.status_code == 201, r.text
    assert [t["track"] for t in r.json()["tracks"]] == ["default", f"t{rh}"]
    tracks = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()["tracks"]
    assert tracks[1]["kit"]["status"] == "ready"
    assert [q["id"] for q in tracks[1]["kit"]["questions"]] == [f"t{rh}-m1"]


@pytest.mark.asyncio
async def test_a_track_can_only_be_added_when_it_makes_sense(
    api_client: AsyncClient, create_scored_app,
) -> None:
    rh = await _template("RH screen")
    old = await _template("Old", active=False)
    unscheduled = await create_scored_app()
    assert (await api_client.post(TRACKS.format(unscheduled),
                                  json={"template_id": rh})).status_code == 409

    app_id = await _scheduled(api_client, create_scored_app)
    assert (await api_client.post(TRACKS.format(app_id), json={"template_id": old})).status_code == 422
    assert (await api_client.post(TRACKS.format(app_id), json={"template_id": rh})).status_code == 201
    assert (await api_client.post(TRACKS.format(app_id), json={"template_id": rh})).status_code == 409
    assert (await api_client.post(TRACKS.format(app_id), json={"template_id": None})).status_code == 409, (
        "the no-template track already exists")


@pytest.mark.asyncio
async def test_a_track_with_feedback_stays(api_client: AsyncClient, seed_tracks) -> None:
    submitted_app, _ = await seed_tracks(submitted=("rh@acme.com",))
    assert (await api_client.delete(f"{TRACKS.format(submitted_app)}/rh")).status_code == 409

    draft_app, users = await seed_tracks(panel={"tech": ["t2@acme.com"], "rh": ["r2@acme.com"]})
    await _write_draft(draft_app, users["r2@acme.com"])
    assert (await api_client.delete(f"{TRACKS.format(draft_app)}/rh")).status_code == 409


@pytest.mark.asyncio
async def test_removing_an_empty_track_takes_its_panel_with_it(
    api_client: AsyncClient, seed_tracks,
) -> None:
    app_id, _ = await seed_tracks()

    r = await api_client.delete(f"{TRACKS.format(app_id)}/rh")

    assert r.status_code == 200, r.text
    assert [t["track"] for t in r.json()["tracks"]] == ["tech"]
    async with _db()() as s:
        left = (await s.execute(select(InterviewAssignment.track).where(
            InterviewAssignment.application_id == app_id))).scalars().all()
    assert left == ["tech"]
    assert (await api_client.delete(f"{TRACKS.format(app_id)}/tech")).status_code == 409, (
        "a round keeps at least one track")
    assert (await api_client.delete(f"{TRACKS.format(app_id)}/nope")).status_code == 404


@pytest.mark.asyncio
async def test_removing_the_unstaffed_track_closes_a_finished_round(
    api_client: AsyncClient, seed_tracks,
) -> None:
    app_id, _ = await seed_tracks(panel={"tech": ["tech@acme.com"]},
                                  submitted=("tech@acme.com",))

    r = await api_client.delete(f"{TRACKS.format(app_id)}/rh")

    assert r.status_code == 200, r.text
    assert (await api_client.get(f"/api/applications/{app_id}")).json()["stage"] == "interviewed"


@pytest.mark.asyncio
async def test_a_closed_round_keeps_its_tracks(api_client: AsyncClient, seed_tracks) -> None:
    app_id, _ = await seed_tracks()
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "interviewed"})
    assert (await api_client.delete(f"{TRACKS.format(app_id)}/rh")).status_code == 409
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/api/test_interview_tracks_api.py -q` (timeout 400000) — expected FAIL (404 on the new routes).

- [ ] **Step 3: The router**

Create `src/recruiter/api/interview_tracks.py`:

```python
"""Adding and removing a parallel interview (track) in the live round.

Only while the application is SCHEDULED: before that there is no round to
add to, and afterwards a closed round's record must not change. Admins and
recruiters only; registered on `_api_router`, so viewers are also refused
by the viewer guard.
"""
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from recruiter.api.candidates import get_engine_dep, get_event_bus
from recruiter.api.deps import get_session, require_role, require_user
from recruiter.api.interview import InterviewKitRead, _read, dispatch_generation
from recruiter.api.interviewers import load_assignments
from recruiter.api.jobs import get_llm_or_none
from recruiter.api.round_tracks import create_track
from recruiter.events import EventBus
from recruiter.llm.client import LLMClient
from recruiter.models import Application, InterviewTemplate, Role, Stage, User
from recruiter.pipeline.interview_sheets import (
    close_round_if_complete,
    rows_in_track,
    sheet_has_content,
)
from recruiter.pipeline.kit_store import kit_for, kits_in_round, track_key

router = APIRouter(prefix="/api", tags=["interview"], dependencies=[Depends(require_user)])


class TrackCreate(BaseModel):
    template_id: int | None = None


async def _scheduled_app(session: AsyncSession, application_id: int) -> Application:
    # Row-locked like every other track mutation (see submit_sheet).
    app_row = await session.get(Application, application_id, with_for_update=True)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    if app_row.stage != Stage.SCHEDULED:
        raise HTTPException(
            status_code=409, detail="tracks change only while the interview is scheduled",
        )
    return app_row


@router.post("/applications/{application_id}/interview-tracks",
             response_model=InterviewKitRead, status_code=status.HTTP_201_CREATED)
async def add_track(
    application_id: int,
    payload: TrackCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    engine: AsyncEngine = Depends(get_engine_dep),
    llm: LLMClient | None = Depends(get_llm_or_none),
    bus: EventBus = Depends(get_event_bus),
    user: User = Depends(require_role(Role.ADMIN, Role.RECRUITER)),
) -> InterviewKitRead:
    app_row = await _scheduled_app(session, application_id)
    template = None
    if payload.template_id is not None:
        template = await session.get(InterviewTemplate, payload.template_id)
        if template is None or not template.is_active:
            raise HTTPException(status_code=422, detail="unknown or archived interview template")
    key = track_key(payload.template_id)
    if await kit_for(session, app_row, track=key) is not None:
        raise HTTPException(status_code=409, detail="this round already has that track")
    await create_track(session, app_row, template, datetime.now(UTC))
    await session.commit()
    await dispatch_generation(
        session, background_tasks, app_row, [key], engine=engine, llm=llm, bus=bus,
    )
    await bus.publish({
        "type": "interview_kit", "application_id": application_id, "status": "generating",
        "job_id": app_row.job_id, "stage_changed": False, "track": key,
    })
    return await _read(session, app_row, user)


@router.delete("/applications/{application_id}/interview-tracks/{track}",
               response_model=InterviewKitRead)
async def remove_track(
    application_id: int,
    track: str,
    session: AsyncSession = Depends(get_session),
    bus: EventBus = Depends(get_event_bus),
    user: User = Depends(require_role(Role.ADMIN, Role.RECRUITER)),
) -> InterviewKitRead:
    """Remove a track nobody has written in, with its (empty) panel. The
    round's last track stays: a scheduled round needs a kit. Removing a
    track can finish the round — the others all staffed and submitted — so
    completion is re-checked, as a panel removal does."""
    app_row = await _scheduled_app(session, application_id)
    kits = await kits_in_round(session, app_row)
    kit_row = next((k for k in kits if k.track == track), None)
    if kit_row is None:
        raise HTTPException(status_code=404, detail=f"no track {track!r} in this round")
    if len(kits) == 1:
        raise HTTPException(status_code=409, detail="a round keeps at least one track")
    panel = rows_in_track(
        await load_assignments(session, application_id), app_row.interview_round, track,
    )
    if any(r.submitted_at is not None or sheet_has_content(r.sheet) for r in panel):
        raise HTTPException(
            status_code=409, detail="someone on this track has already written feedback",
        )
    for row in panel:
        await session.delete(row)
    await session.delete(kit_row)
    await session.flush()
    stage_changed = await close_round_if_complete(session, app_row)
    await session.commit()
    await bus.publish({
        "type": "interview_kit", "application_id": application_id, "status": "ready",
        "job_id": app_row.job_id, "stage_changed": stage_changed, "track": track,
    })
    return await _read(session, app_row, user)
```

In `src/recruiter/main.py`, import `interview_tracks` with the other `recruiter.api` modules (sorted) and add `_api_router.include_router(interview_tracks.router)` next to `interview.router`.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/api/test_interview_tracks_api.py tests/api/test_viewer_matrix.py -q` (timeout 400000) — expected PASS. A viewer-matrix failure naming `/interview-tracks` means the router was registered on `app`.

- [ ] **Step 5: Whole suite, ruff, commit**

Run: `uv run pytest -q` (timeout 400000); ruff — 466 plus the new handlers' B008 only.

```bash
git add src/recruiter/api/interview_tracks.py src/recruiter/main.py tests/api/test_interview_tracks_api.py
git commit -m "feat(interview-kit): add or remove a track while the interview is scheduled

A recruiter can add a parallel track to the live round, generated on
its own, and remove one nobody has written in. The last track stays,
and removing a track re-checks whether the round is now complete.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Frontend — track data and the per-track kit view

**Files:**
- Create: `recruiter-frontend/src/components/candidate/track-kit-view.tsx`
- Modify: `recruiter-frontend/src/hooks/use-interview-kit.ts`, `recruiter-frontend/src/components/candidate/interview-kit-section.tsx`
- Test: `recruiter-frontend/src/hooks/use-interview-kit.test.tsx`

**Interfaces:**
- Consumes: the backend's `tracks` and `?track=` (Tasks 2–3).
- Produces: `TrackRead { track: string; template_id: number | null; template_name: string | null; kit: InterviewKit }`; `SheetRead.track?: string`; `tracksOf(data)`; `useTrackKitActions(applicationId, track: string | null)` → `{ generate, patch, saveSheet, submitSheet, draftQuestion }`; `useInterviewKit(...)` additionally returns `tracks: TrackRead[]`; `TrackKitView` props `{ applicationId, canWrite, interviewRound?, track: string | null, kit, templateName: string | null, sheets: SheetRead[], showHeader?: boolean }`; `errorMessage(err, fallback)` exported from `track-kit-view.tsx`.

This task changes nothing visible: every round renders one track exactly as today. **`interview-kit-section.test.tsx` must pass without any change** — it is the proof.

- [ ] **Step 1: Write the failing hook tests**

In `recruiter-frontend/src/hooks/use-interview-kit.test.tsx`, import `useTrackKitActions` beside `useInterviewKit` and `act` from `@testing-library/react` if absent, then add inside the `describe`:

```tsx
  it("reads a one-track response as a single default track", async () => {
    server.use(
      http.get("http://localhost:8000/api/applications/1/interview-kit", () =>
        HttpResponse.json({ kit: { status: "ready", questions: [] }, sheets: [],
                            template_name: "RH screen" })),
    );
    const { result } = renderHook(() => useInterviewKit(1), { wrapper: wrap() });
    await waitFor(() => expect(result.current.tracks).toHaveLength(1));
    expect(result.current.tracks[0]).toMatchObject({ track: "default", template_name: "RH screen" });
  });

  it("names the track on every request for a named track", async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.post("http://localhost:8000/api/applications/1/interview-kit/generate", ({ request }) => {
        seen.push(new URL(request.url).searchParams.get("track"));
        return HttpResponse.json({ application_id: 1 }, { status: 202 });
      }),
    );
    const { result } = renderHook(() => useTrackKitActions(1, "t5"), { wrapper: wrap() });
    await act(() => result.current.generate.mutateAsync());
    expect(seen).toEqual(["t5"]);
  });
```

(Use the file's existing `server` and `wrap()` helpers; if `wrap()` takes arguments elsewhere in the file, call it the same way.)

Run: `npx vitest --run src/hooks/use-interview-kit.test.tsx` — expected FAIL (`tracks` undefined; `useTrackKitActions` not exported).

- [ ] **Step 2: The hook**

In `recruiter-frontend/src/hooks/use-interview-kit.ts`:

1. In `SheetRead`, after `round?: number;`:

```ts
  /** Which track of that round (phase 3). Optional for safety against an
   *  older server; treat a missing value as "default". */
  track?: string;
```

2. Replace `KitResponse` and `useInterviewKit` with:

```ts
export interface TrackRead {
  track: string;
  template_id: number | null;
  template_name: string | null;
  kit: InterviewKit;
}

interface KitResponse {
  kit: InterviewKit | null;
  sheets: SheetRead[];
  template_name?: string | null;
  /** Every track of the live round the caller may see (phase 3). */
  tracks?: TrackRead[];
}

/** The live round's tracks. A response without `tracks` (an older server,
 *  or a test fixture) is read as the one track its `kit` describes. */
export function tracksOf(data: KitResponse | undefined): TrackRead[] {
  if (!data) return [];
  if (data.tracks) return data.tracks;
  return data.kit
    ? [{ track: "default", template_id: null, template_name: data.template_name ?? null,
         kit: data.kit }]
    : [];
}

/** `?track=` for a named track; a one-track round sends none. */
function withTrack(url: string, track: string | null): string {
  return track === null ? url : `${url}?track=${encodeURIComponent(track)}`;
}

/** The mutations for one track's kit. `track` null means "the round's only
 *  track": requests carry no `?track=`, exactly as before tracks existed. */
export function useTrackKitActions(applicationId: number, track: string | null) {
  const qc = useQueryClient();
  const key = queryKeys.interviewKit(applicationId);
  const path = `/api/applications/${applicationId}/interview-kit`;

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: key });
    qc.invalidateQueries({ queryKey: queryKeys.interviewers(applicationId) });
  };

  const generate = useMutation({
    mutationFn: () => api(withTrack(`${path}/generate`, track), { method: "POST" }),
    onSuccess: invalidate,
  });
```

   …followed by the existing `patch`, `saveSheet`, `submitSheet` and `draftQuestion` mutations, **moved verbatim with their comments**, each URL wrapped: `withTrack(path, track)`, `withTrack(\`${path}/sheet\`, track)`, `withTrack(\`${path}/sheet/submit\`, track)`, `withTrack(\`${path}/draft-question\`, track)`. The function ends with `return { generate, patch, saveSheet, submitSheet, draftQuestion };`. Then:

```ts
export function useInterviewKit(applicationId: number) {
  const query = useQuery({
    queryKey: queryKeys.interviewKit(applicationId),
    queryFn: () => api<KitResponse>(`/api/applications/${applicationId}/interview-kit`),
  });
  const actions = useTrackKitActions(applicationId, null);

  return {
    ...actions,
    kit: query.data?.kit ?? null,
    sheets: query.data?.sheets ?? [],
    templateName: query.data?.template_name ?? null,
    tracks: tracksOf(query.data),
    isLoading: query.isLoading,
    // (keep the existing comment explaining why isError is exposed)
    isError: query.isError,
    refetch: query.refetch,
  };
}
```

- [ ] **Step 3: Extract `TrackKitView`**

Create `recruiter-frontend/src/components/candidate/track-kit-view.tsx`. It receives, moved from `interview-kit-section.tsx`: the `RATINGS` and `VERDICTS` constants, `localIdCounter`/`newQuestionId`, `errorMessage` (now **exported**), and the component body. Its head:

```tsx
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useInterviewers } from "@/hooks/use-interviewers";
import {
  EMPTY_SHEET, type InterviewKit, type InterviewSheet, type KitQuestion, type Rating,
  type SheetRead, type VerdictDecision, useTrackKitActions,
} from "@/hooks/use-interview-kit";
import { FeedbackTable } from "./feedback-table";

// RATINGS, VERDICTS, localIdCounter/newQuestionId moved here verbatim.

export function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.detail : fallback;
}

interface Props {
  applicationId: number;
  canWrite: boolean;
  /** Which round is in progress. Labelled only past the first. */
  interviewRound?: number;
  /** null for a one-track round: requests carry no `?track=` and every
   *  sheet is this track's. */
  track: string | null;
  kit: InterviewKit;
  templateName: string | null;
  /** Every sheet the caller may see — all rounds and, for a recruiter,
   *  all tracks. */
  sheets: SheetRead[];
  /** Tabs already name the track; the section then draws the header. */
  showHeader?: boolean;
}

export function TrackKitView({
  applicationId, canWrite, interviewRound, track, kit, templateName, sheets,
  showHeader = true,
}: Props) {
  const { generate, patch, saveSheet, submitSheet, draftQuestion } =
    useTrackKitActions(applicationId, track);
  // This track's sheets. A sheet's answers are keyed to ONE kit's question
  // ids, so everything below that reasons about "the sheets" means this
  // track's. A one-track round (track null) needs no filter.
  const trackSheets = track === null
    ? sheets
    : sheets.filter((s) => (s.track ?? "default") === track);
```

After that, move **everything** `InterviewKitSection` currently has from `const me = useCurrentUser();` to the end of its JSX, with exactly these edits:

1. `const liveRoundSheets = sheets.filter(...)` → `const liveRoundSheets = trackSheets.filter(...)`.
2. Right after `const mySheetRead = ...`, insert:

```tsx
  // One track per person per round: a recruiter already on another track
  // is not offered this one's sheet — the server would refuse it.
  const mineElsewhere = track !== null && sheets.some(
    (s) => (s.round ?? 1) === liveRound && s.user_id === myId
      && (s.track ?? "default") !== track,
  );
```

   and in `canWriteSheet` change `: (canWrite && liveRoundSheets.length === 0);` to `: (canWrite && liveRoundSheets.length === 0 && !mineElsewhere);`.
3. The `nameById` loop keeps reading all `sheets` (a name is a name on any track).
4. Delete the `if (isLoading) return null;` line, the `if (isError) { … }` block and the `if (!kit) { … }` block — the section keeps those.
5. In the remaining returns — the `generating` one, the `error`-with-no-questions one, and the main one — wrap each `<h3 …>…</h3>` in `{showHeader && ( … )}`.
6. `recordedQuestionIds`: `sheets.filter((s) => s.submitted_at)` → `trackSheets.filter((s) => s.submitted_at)`.
7. `<FeedbackTable questions={draft} sheets={sheets} interviewRound={liveRound} />` → `sheets={trackSheets}`.

Nothing else in the moved code changes.

- [ ] **Step 4: Slim the section**

Replace `recruiter-frontend/src/components/candidate/interview-kit-section.tsx` with:

```tsx
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useInterviewKit } from "@/hooks/use-interview-kit";
import { TrackKitView, errorMessage } from "./track-kit-view";

interface Props {
  applicationId: number;
  canWrite: boolean;
  /** Which round is in progress. Labelled only past the first, where a
   *  reset of every sheet is otherwise indistinguishable from a round
   *  that never happened. */
  interviewRound?: number;
}

export function InterviewKitSection({ applicationId, canWrite, interviewRound }: Props) {
  const { tracks, sheets, isLoading, isError, refetch, generate } =
    useInterviewKit(applicationId);

  if (isLoading) return null;

  if (isError) {
    // (the existing "Couldn't load the interview kit." section, verbatim)
  }

  if (tracks.length === 0) {
    // (the existing no-kit section with the "Generate interview kit"
    //  button, verbatim)
  }

  const first = tracks[0];
  return (
    <TrackKitView
      applicationId={applicationId}
      canWrite={canWrite}
      interviewRound={interviewRound}
      track={tracks.length > 1 ? first.track : null}
      kit={first.kit}
      templateName={first.template_name}
      sheets={sheets}
    />
  );
}
```

Replace the two `// (…verbatim)` comments with the exact JSX those two early returns have today (they move unchanged).

- [ ] **Step 5: Verify — including the unchanged section tests**

Run: `npx vitest --run src/hooks/use-interview-kit.test.tsx src/components/candidate/interview-kit-section.test.tsx src/components/candidate/feedback-table.test.tsx src/routes/application-detail.test.tsx` — expected PASS with **no change** to `interview-kit-section.test.tsx`. If a section test fails, the extraction moved something wrong; fix the component, not the test.
Run: `npx vitest --run` (timeout 400000), `npm run lint`, `npm run build` (timeout 400000) — all pass.

- [ ] **Step 6: Commit**

```bash
git add recruiter-frontend/src
git commit -m "refactor(interview-kit): a per-track kit view and track-aware hooks

The kit section's body becomes TrackKitView, driven by one track's kit,
sheets and mutations; the hooks expose the round's tracks and name a
track on requests when there is more than one. Nothing visible changes:
the section's existing tests pass untouched.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Frontend — tabs, adding and removing tracks

**Files:**
- Create: `recruiter-frontend/src/components/candidate/add-track-dialog.tsx`
- Modify: `recruiter-frontend/src/hooks/use-interview-kit.ts`, `recruiter-frontend/src/hooks/use-interview-templates.ts`, `recruiter-frontend/src/components/candidate/interview-kit-section.tsx`, `recruiter-frontend/src/routes/application-detail.tsx`
- Test: `recruiter-frontend/src/components/candidate/interview-kit-section.test.tsx`

**Interfaces:**
- Consumes: `TrackKitView`, `tracksOf`, `errorMessage` (Task 7); `POST`/`DELETE /interview-tracks` (Task 6).
- Produces: `useTrackMutations(applicationId)` → `{ addTrack, removeTrack }`; `sheetHasContent(sheet)`; `useInterviewTemplates(includeArchived = false, enabled = true)`; `InterviewKitSection` prop `stage?: string`; `AddTrackDialog`.

- [ ] **Step 1: Extend the section test harness and write the failing tests**

In `interview-kit-section.test.tsx`, extend `mountWithKit`:

- `opts` type gains `tracks?: unknown[]; stage?: string; templates?: unknown[]`; `capture` gains `addedTrack?: any; removedTrack?: string`.
- The GET `/interview-kit` handler returns `{ kit, sheets: opts.sheets ?? [], template_name: opts.templateName ?? null, ...(opts.tracks ? { tracks: opts.tracks } : {}) }`.
- Add handlers:

```ts
    http.get("http://localhost:8000/api/interview-templates", () =>
      HttpResponse.json(opts.templates ?? [])),
    http.post("http://localhost:8000/api/applications/1/interview-tracks", async ({ request }) => {
      capture.addedTrack = await request.json();
      return HttpResponse.json({ kit, sheets: opts.sheets ?? [], tracks: opts.tracks ?? [] },
                               { status: 201 });
    }),
    http.delete("http://localhost:8000/api/applications/1/interview-tracks/:track", ({ params }) => {
      capture.removedTrack = String(params.track);
      return HttpResponse.json({ kit, sheets: opts.sheets ?? [], tracks: opts.tracks ?? [] });
    }),
```

- The render passes `stage={opts.stage}` to `InterviewKitSection`.

No existing test's expectations change. Then add:

```tsx
const q = (id: string, text: string) =>
  ({ id, text, source: "baseline", answer: null, rating: null });
const TECH = { track: "t1", template_id: 1, template_name: "Technical",
               kit: { status: "ready", questions: [q("q1", "Clusters?")] } };
const RH = { track: "t2", template_id: 2, template_name: "RH screen",
             kit: { status: "ready", questions: [q("r1", "Why us?")] } };
const TEMPLATE = (id: number, name: string) => ({ id, name, description: null, questions: [],
  probe_mode: "none", include_job_questions: false, is_active: true });

describe("InterviewKitSection — tracks", () => {
  it("shows one tab per track, each with its own questions", async () => {
    mountWithKit(TECH.kit, {}, { tracks: [TECH, RH] });
    const rhTab = await screen.findByRole("tab", { name: /rh screen/i });
    expect(screen.getByRole("tab", { name: /technical/i })).toHaveAttribute("aria-selected", "true");
    await userEvent.click(rhTab);
    expect(rhTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: /rh screen/i })).toHaveTextContent("Why us?");
  });

  it("adds a track from the templates the round does not have", async () => {
    const capture: { addedTrack?: any } = {};
    mountWithKit(TECH.kit, capture, {
      tracks: [TECH], stage: "scheduled",
      templates: [TEMPLATE(1, "Technical"), TEMPLATE(2, "RH screen")],
    });
    await userEvent.click(await screen.findByRole("button", { name: /add track/i }));
    await userEvent.click(screen.getByRole("combobox", { name: /track template/i }));
    expect(screen.queryByRole("option", { name: "Technical" })).not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole("option", { name: /rh screen/i }));
    await userEvent.click(screen.getByRole("button", { name: /^add track$/i }));
    await waitFor(() => expect(capture.addedTrack).toEqual({ template_id: 2 }));
  });

  it("will not remove a track someone has written in", async () => {
    const capture: { removedTrack?: string } = {};
    mountWithKit(TECH.kit, capture, {
      tracks: [TECH, RH], stage: "scheduled",
      sheets: [{ user_id: 7, name: "Carol", email: "c@acme.com", round: 1, track: "t2",
                 submitted_at: null,
                 sheet: { answers: {}, verdict: { decision: null, note: "promising" } } }],
    });
    expect(await screen.findByRole("button", { name: /remove track rh screen/i })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /remove track technical/i }));
    await waitFor(() => expect(capture.removedTrack).toBe("t1"));
  });

  it("shows an interviewer their one track without tabs", async () => {
    mountWithKit(RH.kit, {}, { tracks: [RH], me: { id: 7, role: "viewer" }, canWrite: false });
    expect(await screen.findByText("Why us?")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.getByText(/rh screen/i)).toBeInTheDocument();
  });
});
```

Run: `npx vitest --run src/components/candidate/interview-kit-section.test.tsx` — expected: the four new tests FAIL, every existing one PASSES.

- [ ] **Step 2: Hooks**

`use-interview-templates.ts` — `useInterviewTemplates(includeArchived = false, enabled = true)`, passing `enabled` to `useQuery`.

`use-interview-kit.ts` — append:

```ts
/** Whether a sheet holds anything a recruiter would not want discarded —
 *  mirrors the server's sheet_has_content. */
export function sheetHasContent(sheet: InterviewSheet): boolean {
  return Object.values(sheet.answers).some((a) => a?.answer || a?.rating)
    || !!(sheet.verdict.decision || sheet.verdict.note);
}

/** Adding and removing a track of the live round. Both return the full kit
 *  read, cached as-is. */
export function useTrackMutations(applicationId: number) {
  const qc = useQueryClient();
  const key = queryKeys.interviewKit(applicationId);
  const path = `/api/applications/${applicationId}/interview-tracks`;
  const settle = (data: KitResponse) => {
    qc.setQueryData(key, data);
    qc.invalidateQueries({ queryKey: key });
    qc.invalidateQueries({ queryKey: queryKeys.interviewers(applicationId) });
    // Removing the last unfinished track can close the round.
    qc.invalidateQueries({ queryKey: queryKeys.application(applicationId) });
  };
  const addTrack = useMutation({
    mutationFn: (templateId: number | null) =>
      api<KitResponse>(path, { method: "POST", json: { template_id: templateId } }),
    onSuccess: settle,
  });
  const removeTrack = useMutation({
    mutationFn: (track: string) =>
      api<KitResponse>(`${path}/${encodeURIComponent(track)}`, { method: "DELETE" }),
    onSuccess: settle,
  });
  return { addTrack, removeTrack };
}
```

- [ ] **Step 3: `AddTrackDialog`**

Create `recruiter-frontend/src/components/candidate/add-track-dialog.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

export interface TrackOption {
  templateId: number | null;
  label: string;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Tracks this round does not have yet. */
  options: TrackOption[];
  onConfirm: (templateId: number | null) => void;
  pending?: boolean;
}

const NONE = "none";
const valueOf = (o: TrackOption) => (o.templateId === null ? NONE : String(o.templateId));

export function AddTrackDialog({ open, onOpenChange, options, onConfirm, pending }: Props) {
  const first = options[0] ? valueOf(options[0]) : "";
  const [choice, setChoice] = useState(first);
  useEffect(() => { if (open) setChoice(first); }, [open, first]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a track</DialogTitle>
          <DialogDescription>
            A parallel interview in this round, with its own questions, interviewers and sheets.
          </DialogDescription>
        </DialogHeader>
        <Select value={choice} onValueChange={setChoice}>
          <SelectTrigger aria-label="Track template"><SelectValue /></SelectTrigger>
          <SelectContent>
            {options.map((o) => (
              <SelectItem key={valueOf(o)} value={valueOf(o)}>{o.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={pending || !choice}
            onClick={() => onConfirm(choice === NONE ? null : Number(choice))}>
            Add track
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 4: The section with tabs**

Replace `interview-kit-section.tsx` with:

```tsx
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useInterviewTemplates } from "@/hooks/use-interview-templates";
import {
  type SheetRead, type TrackRead, sheetHasContent, useInterviewKit, useTrackMutations,
} from "@/hooks/use-interview-kit";
import { AddTrackDialog, type TrackOption } from "./add-track-dialog";
import { TrackKitView, errorMessage } from "./track-kit-view";

interface Props {
  applicationId: number;
  canWrite: boolean;
  /** Which round is in progress. Labelled only past the first, where a
   *  reset of every sheet is otherwise indistinguishable from a round
   *  that never happened. */
  interviewRound?: number;
  /** The application's stage: tracks are added and removed only while the
   *  interview is scheduled. */
  stage?: string;
}

const trackLabel = (t: TrackRead) => t.template_name ?? "No template";

export function InterviewKitSection({ applicationId, canWrite, interviewRound, stage }: Props) {
  const { tracks, sheets, isLoading, isError, refetch, generate } =
    useInterviewKit(applicationId);
  const { addTrack, removeTrack } = useTrackMutations(applicationId);
  const canChangeTracks = canWrite && stage === "scheduled";
  const templates = useInterviewTemplates(false, canChangeTracks).data ?? [];
  const [addOpen, setAddOpen] = useState(false);
  const [active, setActive] = useState<string | null>(null);

  if (isLoading) return null;
  if (isError) {
    // Keep this block's JSX exactly as it is in the file (the "Couldn't
    // load the interview kit." section with its Retry button).
  }
  if (tracks.length === 0) {
    // Keep this block's JSX exactly as it is in the file (the section with
    // the "Generate interview kit" button).
  }

  const liveRound = interviewRound ?? 1;
  const liveSheets = (track: string): SheetRead[] =>
    sheets.filter((s) => (s.round ?? 1) === liveRound && (s.track ?? "default") === track);

  // Tracks this round does not have yet: every active template not in use,
  // and the no-template track when the round lacks it.
  const used = new Set(tracks.map((t) => t.template_id));
  const options: TrackOption[] = [
    ...(used.has(null) ? [] : [{ templateId: null, label: "No template" }]),
    ...templates.filter((t) => !used.has(t.id)).map((t) => ({ templateId: t.id, label: t.name })),
  ];
  const addButton = canChangeTracks && options.length > 0 && (
    <Button variant="outline" size="sm" onClick={() => setAddOpen(true)}>+ Add track</Button>
  );
  const addDialog = (
    <AddTrackDialog
      open={addOpen}
      onOpenChange={setAddOpen}
      options={options}
      pending={addTrack.isPending}
      onConfirm={(templateId) =>
        addTrack.mutate(templateId, {
          onSuccess: () => setAddOpen(false),
          onError: (err) => toast.error(errorMessage(err, "Couldn't add the track")),
        })}
    />
  );

  if (tracks.length === 1) {
    const only = tracks[0];
    const view = (
      <TrackKitView
        applicationId={applicationId}
        canWrite={canWrite}
        interviewRound={interviewRound}
        track={null}
        kit={only.kit}
        templateName={only.template_name}
        sheets={sheets}
      />
    );
    // Nothing to add (no templates, or all in use): exactly today's view.
    if (!addButton) return view;
    return (
      <div className="space-y-3">
        {view}
        {addButton}
        {addDialog}
      </div>
    );
  }

  // A removed track's tab falls back to the first one.
  const current = tracks.some((t) => t.track === active) ? (active as string) : tracks[0].track;

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-lg font-semibold">
          Interview kit
          {liveRound > 1 && (
            <span className="ml-2 text-xs font-normal uppercase tracking-[0.18em] text-muted-foreground">
              Round {liveRound}
            </span>
          )}
        </h3>
        {addButton}
      </div>
      <Tabs value={current} onValueChange={setActive}>
        <TabsList>
          {tracks.map((t) => {
            const panel = liveSheets(t.track);
            const done = panel.filter((s) => s.submitted_at).length;
            return (
              <TabsTrigger key={t.track} value={t.track}>
                {trackLabel(t)}
                <span className="ml-2 text-xs text-muted-foreground">
                  {t.kit.status === "generating" ? "…"
                    : panel.length === 0 ? "no interviewers" : `${done}/${panel.length}`}
                </span>
              </TabsTrigger>
            );
          })}
        </TabsList>
        {tracks.map((t) => {
          const written = liveSheets(t.track)
            .some((s) => s.submitted_at || sheetHasContent(s.sheet));
          return (
            // Every track stays mounted, hidden when inactive, so unsaved
            // edits in one track survive switching to another.
            <TabsContent key={t.track} value={t.track} forceMount
              className="space-y-3 data-[state=inactive]:hidden">
              {canChangeTracks && (
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-auto px-2 py-1 text-xs"
                    aria-label={`Remove track ${trackLabel(t)}`}
                    disabled={written || removeTrack.isPending}
                    onClick={() => removeTrack.mutate(t.track, {
                      onError: (err) =>
                        toast.error(errorMessage(err, "Couldn't remove the track")),
                    })}
                  >
                    Remove track
                  </Button>
                  {written && (
                    <span className="text-xs text-muted-foreground">
                      Someone on this track has written feedback.
                    </span>
                  )}
                </div>
              )}
              <TrackKitView
                applicationId={applicationId}
                canWrite={canWrite}
                interviewRound={interviewRound}
                track={t.track}
                kit={t.kit}
                templateName={t.template_name}
                sheets={sheets}
                showHeader={false}
              />
            </TabsContent>
          );
        })}
      </Tabs>
      {addDialog}
    </section>
  );
}
```

The two `// Keep this block's JSX…` comments stand for the existing early returns in the file, which do not change — leave that JSX in place rather than retyping it.

In `routes/application-detail.tsx`, pass `stage={application.data.stage}` to `InterviewKitSection`.

- [ ] **Step 5: Verify**

Run: `npx vitest --run src/components/candidate/interview-kit-section.test.tsx src/routes/application-detail.test.tsx` — expected PASS (new and existing).
Run: `npx vitest --run` (timeout 400000), `npm run lint`, `npm run build` (timeout 400000) — all pass.

- [ ] **Step 6: Commit**

```bash
git add recruiter-frontend/src
git commit -m "feat(interview-kit): tabs for parallel tracks, and adding or removing one

A round with several tracks shows one tab each, with its submitted
count, and every tab stays mounted so unsaved edits survive switching.
Recruiters add a track from the templates the round lacks, and remove
one nobody has written in. A one-track round looks as before.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Frontend — multi-track round picker and per-track panel

**Files:**
- Modify: `recruiter-frontend/src/components/candidate/schedule-round-dialog.tsx`, `recruiter-frontend/src/components/candidate/action-bar.tsx`, `recruiter-frontend/src/hooks/use-application-mutations.ts`, `recruiter-frontend/src/hooks/use-interviewers.ts`, `recruiter-frontend/src/components/candidate/interviewers-picker.tsx`, `recruiter-frontend/src/routes/application-detail.tsx`
- Test: `schedule-round-dialog.test.tsx` (rewritten), `action-bar.test.tsx`, `interviewers-picker.test.tsx`

**Interfaces:**
- Consumes: `TrackRead`, `useInterviewKit(...).tracks` (Task 7); `interview_template_ids` (Task 5); `PUT /interviewers?track=` (Task 4).
- Produces: `ScheduleRoundDialog` props `{ open, onOpenChange, title, templates, preselected: (number | null)[], onConfirm(templateIds: (number | null)[]), pending? }`; `markScheduled(templateIds?)` / `reopenRound(templateIds?)`; `InterviewerRead.track?: string`; `setInterviewers.mutate(number[] | { userIds: number[]; track: string })`; `InterviewersPicker` prop `tracks?: TrackRead[]`.

- [ ] **Step 1: Rewrite the dialog tests (the picker becomes multi-select by design)**

Replace `schedule-round-dialog.test.tsx` with:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ScheduleRoundDialog } from "./schedule-round-dialog";

const T = (id: number, name: string) => ({
  id, name, description: null, questions: [], probe_mode: "none" as const,
  include_job_questions: false, is_active: true,
});

function mount(preselected: (number | null)[], onConfirm = vi.fn()) {
  render(<ScheduleRoundDialog open onOpenChange={() => {}} title="Schedule interview"
    templates={[T(1, "Technical"), T(2, "RH screen")]} preselected={preselected}
    onConfirm={onConfirm} />);
  return onConfirm;
}

describe("ScheduleRoundDialog", () => {
  it("preselects the given templates and confirms them", async () => {
    const onConfirm = mount([2]);
    expect(screen.getByRole("checkbox", { name: "RH screen" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Technical" })).not.toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: /^schedule$/i }));
    expect(onConfirm).toHaveBeenCalledWith([2]);
  });

  it("confirms several tracks, No template first, then list order", async () => {
    const onConfirm = mount([2]);
    await userEvent.click(screen.getByRole("checkbox", { name: "Technical" }));
    await userEvent.click(screen.getByRole("checkbox", { name: /no template/i }));
    await userEvent.click(screen.getByRole("button", { name: /^schedule$/i }));
    expect(onConfirm).toHaveBeenCalledWith([null, 1, 2]);
  });

  it("falls back to No template when the preselection is archived or unknown", () => {
    mount([99]);
    expect(screen.getByRole("checkbox", { name: /no template/i })).toBeChecked();
  });

  it("cannot schedule with nothing ticked", async () => {
    mount([1]);
    await userEvent.click(screen.getByRole("checkbox", { name: "Technical" }));
    expect(screen.getByRole("button", { name: /^schedule$/i })).toBeDisabled();
  });
});
```

Run it — expected FAIL (the dialog is still single-select).

- [ ] **Step 2: The multi-select dialog**

Replace `schedule-round-dialog.tsx` with:

```tsx
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import type { InterviewTemplate } from "@/hooks/use-interview-templates";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** Active templates only. */
  templates: InterviewTemplate[];
  /** Ticked when the dialog opens: the job's default on first scheduling,
   *  the previous round's tracks on "Another round". Archived or unknown
   *  ids are dropped; if nothing is left, "No template" is ticked. */
  preselected: (number | null)[];
  /** The ticked choices — "No template" (null) first, then templates in
   *  list order, the order the round's tracks are created and shown in. */
  onConfirm: (templateIds: (number | null)[]) => void;
  pending?: boolean;
}

export function ScheduleRoundDialog({
  open, onOpenChange, title, templates, preselected, onConfirm, pending,
}: Props) {
  const activeIds = new Set(templates.map((t) => t.id));
  const kept = preselected.filter((id) => id === null || activeIds.has(id));
  // A string key, so a fresh-but-equal array each render does not re-run
  // the reset below and wipe what the user ticked.
  const initialKey = JSON.stringify(kept.length > 0 ? kept : [null]);
  const [chosen, setChosen] = useState<(number | null)[]>(() => JSON.parse(initialKey));
  useEffect(() => { if (open) setChosen(JSON.parse(initialKey)); }, [open, initialKey]);

  const options = [
    { id: null as number | null, label: "No template — the job's own questions" },
    ...templates.map((t) => ({ id: t.id as number | null, label: t.name })),
  ];
  const ordered = options.map((o) => o.id).filter((id) => chosen.includes(id));
  const toggle = (id: number | null, on: boolean) =>
    setChosen((c) => (on ? [...c, id] : c.filter((x) => x !== id)));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            Each ticked template becomes a track — its own questions, interviewers and
            sheets, run in parallel.
          </DialogDescription>
        </DialogHeader>
        <ul className="space-y-1">
          {options.map((o) => (
            <li key={o.id ?? "none"}>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={chosen.includes(o.id)}
                  onChange={(e) => toggle(o.id, e.target.checked)}
                />
                {o.label}
              </label>
            </li>
          ))}
        </ul>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={pending || ordered.length === 0} onClick={() => onConfirm(ordered)}>
            Schedule
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

Run the dialog tests — expected PASS.

- [ ] **Step 3: Mutations and the action bar**

`use-application-mutations.ts` — in `PatchPayload` replace `interview_template_id?: number | null;` with `interview_template_ids?: (number | null)[];`, and replace `markScheduled`/`reopenRound` (keep their existing comments) with:

```ts
  // `undefined` omits the choice so the server applies the job's default;
  // a list is sent as the round's tracks.
  const schedule = (templateIds?: (number | null)[]) =>
    patch.mutate(templateIds === undefined
      ? { stage: "scheduled" }
      : { stage: "scheduled", interview_template_ids: templateIds });
```

with `markScheduled: schedule,` and `reopenRound: schedule,` in the returned object (define `schedule` above the `return`).

`action-bar.tsx`:
- read `const kitTracks = useInterviewKit(application.id).tracks;` (import from `@/hooks/use-interview-kit`);
- compute, before the JSX:

```tsx
  // First scheduling offers the job's default; "Another round" offers the
  // tracks the closing round ran, so "the same again" is one click.
  const preselected = pickerFor === "reopen" && kitTracks.length > 0
    ? kitTracks.map((t) => t.template_id)
    : [job.data?.default_interview_template_id ?? null];
```

- the dialog gets `preselected={preselected}` instead of `defaultTemplateId=…`, and `onConfirm={(templateIds) => { if (pickerFor === "reopen") m.reopenRound(templateIds); else m.markScheduled(templateIds); setPickerFor(null); }}`.

Add to `action-bar.test.tsx` (import `queryKeys` if not already):

```tsx
  it("offers the previous round's tracks for another round", async () => {
    const t = (id: number, name: string) => ({ id, name, description: null, questions: [],
      probe_mode: "none", include_job_questions: false, is_active: true });
    const templates = [t(1, "Technical"), t(2, "RH screen"), t(3, "Culture")];
    const kit = { kit: null, sheets: [], tracks: [
      { track: "t1", template_id: 1, template_name: "Technical", kit: { status: "ready", questions: [] } },
      { track: "t2", template_id: 2, template_name: "RH screen", kit: { status: "ready", questions: [] } },
    ] };
    apiMock.mockImplementation(async (path: string) =>
      path.startsWith("/api/interview-templates") ? templates
        : path.endsWith("/interview-kit") ? kit : {});
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    qc.setQueryData(queryKeys.interviewTemplates(false), templates);
    qc.setQueryData(queryKeys.interviewKit(1), kit);
    render(
      <QueryClientProvider client={qc}>
        <ActionBar application={baseApp({ stage: "interviewed" })} candidateEmail="alice@example.com" />
      </QueryClientProvider>,
    );

    await userEvent.click(screen.getByRole("button", { name: /another round/i }));

    expect(await screen.findByRole("checkbox", { name: "Technical" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "RH screen" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Culture" })).not.toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: /^schedule$/i }));
    await waitFor(() => expect(apiMock).toHaveBeenCalledWith("/api/applications/1", {
      method: "PATCH", json: { stage: "scheduled", interview_template_ids: [1, 2] },
    }));
  });
```

- [ ] **Step 4: Per-track panel**

`use-interviewers.ts` — `InterviewerRead` gains `track?: string;` (comment: "Which track of the live round (phase 3); absent from older servers."). Replace the `setInterviewers` mutationFn with:

```ts
    // A bare list is the whole panel of a one-track round; `{ userIds,
    // track }` sets one track's panel (`?track=`).
    mutationFn: (arg: number[] | { userIds: number[]; track: string }) => {
      const { userIds, track } = Array.isArray(arg) ? { userIds: arg, track: null } : arg;
      const url = track === null ? path : `${path}?track=${encodeURIComponent(track)}`;
      return api<InterviewerRead[]>(url, { method: "PUT", json: { user_ids: userIds } });
    },
```

`interviewers-picker.tsx`:
- Props gain `tracks?: TrackRead[]` (import the type from `@/hooks/use-interview-kit`), documented "The live round's tracks. With two or more, the panel is shown and edited per track; otherwise exactly as before tracks." Destructure `tracks = []`.
- Replace `const [open, setOpen] = useState(false);` with:

```tsx
  // The track whose panel the dialog edits: undefined = closed; null = the
  // whole panel of a one-track round (no ?track= sent).
  const [editing, setEditing] = useState<string | null | undefined>(undefined);
  const open = editing !== undefined;
  const perTrack = tracks.length > 1;
  const labelOf = (track: string | undefined) => {
    const t = tracks.find((x) => x.track === track);
    return t ? (t.template_name ?? "No template") : (track ?? "");
  };
  // One track per person per round: someone on another track is shown but
  // cannot be ticked here.
  const onOtherTrack = (userId: number) =>
    editing ? interviewers.find((i) => i.user_id === userId && i.track !== editing) : undefined;
```

- `openDialog` takes `track: string | null`: `setChecked(interviewers.filter((i) => track === null || i.track === track).map((i) => i.user_id)); setFilter(""); setEditing(track);`. `useUserDirectory(open)` keeps working.
- `inactiveAssigned` additionally filters `(i) => !editing || i.track === editing`.
- Chips: when `!perTrack`, the current chips block and `Assign` button stay exactly as they are, with `onClick={() => openDialog(null)}`. When `perTrack`, render instead, for each track:

```tsx
        <div key={t.track} className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">{labelOf(t.track)}:</span>
          {interviewers.filter((i) => i.track === t.track).map((i) => (
            <span key={i.user_id}
              className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-xs">
              {i.name ?? i.email}
              {i.submitted_at && <span aria-label="submitted" className="text-success">✓</span>}
            </span>
          ))}
          {canWrite && (
            <Button variant="outline" size="sm" className="h-auto px-2 py-1 text-xs"
              aria-label={`Assign interviewers to ${labelOf(t.track)}`}
              onClick={() => openDialog(t.track)}
              disabled={interviewersLoading || interviewersError}>
              Assign
            </Button>
          )}
        </div>
```

  (keep the leading "interviewers:" label and the loading/error texts as they are).
- Dialog: `open={open}`, `onOpenChange={(o) => { if (!o) setEditing(undefined); }}`, title `{editing ? \`Assign interviewers — ${labelOf(editing)}\` : "Assign interviewers"}`. In each directory row, compute `const other = onOtherTrack(u.id);`, add `disabled={!!other}` to the checkbox, and after the label text render `{other && <span className="text-muted-foreground"> (on {labelOf(other.track)})</span>}`.
- Save: `setInterviewers.mutate(editing ? { userIds: checked, track: editing } : checked, { onSuccess: () => setEditing(undefined), onError: … })`; Cancel: `setEditing(undefined)`.

`application-detail.tsx` — call `const kit = useInterviewKit(id);` next to the other hooks (before any early return) and pass `tracks={kit.tracks}` to `InterviewersPicker`.

Add to `interviewers-picker.test.tsx` (add `import type { TrackRead } from "@/hooks/use-interview-kit";` to its imports):

```tsx
  it("edits one track's panel when the round has several", async () => {
    const capture: { body?: any; url?: string } = {};
    server.use(
      http.get("http://localhost:8000/api/applications/1/interviewers", () =>
        HttpResponse.json([{ user_id: 2, name: "Bob", email: "bob@acme.com",
                             submitted_at: null, track: "t1" }])),
      http.get("http://localhost:8000/api/users/directory", () =>
        HttpResponse.json([
          { id: 2, name: "Bob", email: "bob@acme.com", role: "viewer" },
          { id: 3, name: null, email: "carol@acme.com", role: "recruiter" },
        ])),
      http.put("http://localhost:8000/api/applications/1/interviewers", async ({ request }) => {
        capture.url = request.url;
        capture.body = await request.json();
        return HttpResponse.json([]);
      }),
    );
    const tracks: TrackRead[] = [
      { track: "t1", template_id: 1, template_name: "Technical",
        kit: { status: "ready", questions: [] } },
      { track: "t2", template_id: 2, template_name: "RH screen",
        kit: { status: "ready", questions: [] } },
    ];
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={qc}>
        <InterviewersPicker applicationId={1} canWrite tracks={tracks} />
      </QueryClientProvider>,
    );

    await userEvent.click(await screen.findByRole("button", { name: /assign interviewers to rh screen/i }));

    expect(await screen.findByRole("checkbox", { name: /bob/i })).toBeDisabled();
    expect(screen.getByText(/on technical/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: /carol@acme.com/i }));
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(capture.body).toEqual({ user_ids: [3] }));
    expect(new URL(capture.url!).searchParams.get("track")).toBe("t2");
  });
```

- [ ] **Step 5: Verify**

Run: `npx vitest --run src/components/candidate/schedule-round-dialog.test.tsx src/components/candidate/action-bar.test.tsx src/components/candidate/interviewers-picker.test.tsx src/routes/application-detail.test.tsx` — expected PASS, the existing action-bar and picker tests unchanged.
Run: `npx vitest --run` (timeout 400000), `npm run lint`, `npm run build` (timeout 400000); from the repo root `uv run pytest -q` (timeout 400000) — all pass.

- [ ] **Step 6: Commit**

```bash
git add recruiter-frontend/src
git commit -m "feat(interview-kit): pick several tracks when a round starts, staff each one

The round-start picker becomes a checklist; another round preselects
the tracks the last one ran. With several tracks the panel is shown
and assigned per track, and someone already on one track cannot be
ticked for another. One-track rounds keep the single picker and panel.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```
