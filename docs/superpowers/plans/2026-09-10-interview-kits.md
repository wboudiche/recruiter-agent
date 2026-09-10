# Interview Kits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate interview questions per candidate from their score rationales, let the recruiter edit them before the call and record answers plus an advisory rating during it.

**Architecture:** Two JSON columns (`jobs.interview_baseline`, `applications.interview_kit`) following the repo's existing `criteria` / `score_breakdown` / `enrichment` idiom. A kit snapshots the job baseline plus LLM-generated probes. Generation runs as a FastAPI background task enqueued *after* the stage transition commits, so an LLM failure can never break the finite-state machine.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x (`Mapped`), Pydantic v2, Alembic, pytest; React 18, TanStack Query, Tailwind, vitest + msw, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-10-interview-kits-design.md`

## Global Constraints

- Backend tests run with `uv run pytest`; frontend with `npx vitest --run`; typecheck with `npm run lint` (which is `tsc --noEmit`).
- `ruff check src/` must not exceed its pre-existing baseline of **233** errors. Keep lines ≤ 100 chars.
- Every LLM call uses `max_tokens=2048` minimum. Never 512 — reasoning tokens count against the budget and exhaust it (PR #17).
- Write endpoints require the recruiter role via `require_role`; reads are open to any authenticated user.
- Frontend write controls gate on a `canWrite` prop, as `EnrichmentSection` and `ActionBar` already do.
- Rating values are exactly `"strong" | "adequate" | "weak"` or null. Kit status is exactly `"generating" | "ready" | "error"`.

---

### Task 1: Persistence — columns, models, kit schemas

**Files:**
- Create: `alembic/versions/20260910_000000_interview_kits.py`
- Create: `src/recruiter/schemas/interview.py`
- Modify: `src/recruiter/models/job.py`, `src/recruiter/models/application.py`
- Test: `tests/unit/test_interview_schemas.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `KitQuestion`, `InterviewKit`, `BaselineQuestion` (Pydantic v2 models) from `recruiter.schemas.interview`; columns `Job.interview_baseline: Mapped[list[dict] | None]` and `Application.interview_kit: Mapped[dict | None]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_interview_schemas.py
import pytest
from pydantic import ValidationError

from recruiter.schemas.interview import BaselineQuestion, InterviewKit, KitQuestion


def test_kit_question_round_trips_through_json() -> None:
    q = KitQuestion(id="q1", text="Describe a production incident.", source="probe",
                    criterion="Kubernetes", answer=None, rating=None)
    assert KitQuestion.model_validate(q.model_dump()) == q


def test_rating_rejects_values_outside_the_three_allowed() -> None:
    with pytest.raises(ValidationError):
        KitQuestion(id="q1", text="t", source="probe", rating="excellent")


def test_status_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError):
        InterviewKit(status="finished", questions=[])


def test_empty_question_text_is_rejected() -> None:
    """A blank question is not a question; it would render as an empty row."""
    with pytest.raises(ValidationError):
        BaselineQuestion(id="b1", text="   ")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_interview_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'recruiter.schemas.interview'`

- [ ] **Step 3: Write the schemas**

```python
# src/recruiter/schemas/interview.py
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Rating = Literal["strong", "adequate", "weak"]
KitStatus = Literal["generating", "ready", "error"]
QuestionSource = Literal["baseline", "probe"]


class _TextQuestion(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=2000)
    criterion: str | None = Field(default=None, max_length=200)

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question text cannot be blank")
        return v.strip()


class BaselineQuestion(_TextQuestion):
    """A question every candidate for this role is asked."""


class KitQuestion(_TextQuestion):
    source: QuestionSource
    answer: str | None = Field(default=None, max_length=20000)
    rating: Rating | None = None


class InterviewKit(BaseModel):
    status: KitStatus
    error: str | None = None
    generated_at: str | None = None
    submitted_at: str | None = None
    questions: list[KitQuestion] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_interview_schemas.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Add the model columns**

```python
# src/recruiter/models/job.py — beside `criteria`
    interview_baseline: Mapped[list[dict] | None] = mapped_column(JSON)

# src/recruiter/models/application.py — beside `enrichment`
    interview_kit: Mapped[dict | None] = mapped_column(JSON)
```

- [ ] **Step 6: Write the migration**

```python
# alembic/versions/20260910_000000_interview_kits.py
"""add interview baseline (job) and interview kit (application) columns

Revision ID: c4e1a90b7d32
Revises: 8af6fd614b13
Create Date: 2026-09-10 00:00:00.000000

Interview kits: a per-job baseline of shared questions, and a per-application
kit holding the snapshotted baseline plus generated probes with answers and
ratings. Both JSON, matching criteria/score_breakdown/enrichment.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c4e1a90b7d32'
down_revision: Union[str, None] = '8af6fd614b13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("interview_baseline", sa.JSON(), nullable=True))
    op.add_column("applications", sa.Column("interview_kit", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("applications", "interview_kit")
    op.drop_column("jobs", "interview_baseline")
```

- [ ] **Step 7: Verify the migration applies and reverses**

Run: `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: three successful runs, no error. CONTRIBUTING requires testing the downgrade path.

- [ ] **Step 8: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all pass (nothing else touches these columns yet)

- [ ] **Step 9: Commit**

```bash
git add alembic/versions/20260910_000000_interview_kits.py src/recruiter/schemas/interview.py \
        src/recruiter/models/job.py src/recruiter/models/application.py \
        tests/unit/test_interview_schemas.py
git commit -m "feat(interview): add interview_baseline and interview_kit columns"
```

---

### Task 2: Kit assembly — the merge and preservation rules

Pure functions, no DB and no LLM. This is where the spec's two hardest rules live, so they are tested in isolation before anything calls them.

**Files:**
- Create: `src/recruiter/pipeline/interview_kit.py`
- Test: `tests/unit/test_interview_kit_assembly.py`

**Interfaces:**
- Consumes: `BaselineQuestion`, `KitQuestion`, `InterviewKit` from Task 1.
- Produces: `build_kit(baseline: list[BaselineQuestion], probes: list[str], *, criteria_by_probe: list[str | None], now: str) -> InterviewKit` and `merge_regenerated(existing: InterviewKit, baseline: list[BaselineQuestion], probes: list[str], *, criteria_by_probe: list[str | None], now: str) -> InterviewKit`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_interview_kit_assembly.py
from recruiter.pipeline.interview_kit import build_kit, merge_regenerated
from recruiter.schemas.interview import BaselineQuestion, InterviewKit, KitQuestion

NOW = "2026-09-10T10:00:00+00:00"


def _baseline() -> list[BaselineQuestion]:
    return [BaselineQuestion(id="b1", text="Why this role?"),
            BaselineQuestion(id="b2", text="Notice period?")]


def test_build_kit_puts_baseline_first_then_probes() -> None:
    kit = build_kit(_baseline(), ["Describe a K8s incident."],
                    criteria_by_probe=["Kubernetes"], now=NOW)
    assert [q.source for q in kit.questions] == ["baseline", "baseline", "probe"]
    assert [q.text for q in kit.questions][:2] == ["Why this role?", "Notice period?"]
    assert kit.questions[2].criterion == "Kubernetes"
    assert kit.status == "ready"
    assert kit.generated_at == NOW


def test_build_kit_gives_every_question_a_unique_id() -> None:
    kit = build_kit(_baseline(), ["p one", "p two"], criteria_by_probe=[None, None], now=NOW)
    ids = [q.id for q in kit.questions]
    assert len(ids) == len(set(ids))


def test_regeneration_keeps_answered_questions_untouched() -> None:
    """Losing typed interview notes to a stray Retry would be unforgivable."""
    existing = InterviewKit(status="ready", questions=[
        KitQuestion(id="b1", text="Why this role?", source="baseline",
                    answer="Wants scale", rating="strong"),
        KitQuestion(id="p1", text="Old probe", source="probe", answer=None),
    ])
    merged = merge_regenerated(existing, _baseline(), ["Fresh probe"],
                               criteria_by_probe=[None], now=NOW)

    answered = [q for q in merged.questions if q.answer is not None]
    assert len(answered) == 1
    assert answered[0].text == "Why this role?"
    assert answered[0].answer == "Wants scale"
    assert answered[0].rating == "strong"
    assert "Old probe" not in [q.text for q in merged.questions]
    assert "Fresh probe" in [q.text for q in merged.questions]


def test_regeneration_re_snapshots_unanswered_baseline_questions() -> None:
    """Explicit regeneration should pick up the role's current questions."""
    existing = InterviewKit(status="ready", questions=[
        KitQuestion(id="b1", text="Stale baseline wording", source="baseline", answer=None),
    ])
    merged = merge_regenerated(existing, _baseline(), [], criteria_by_probe=[], now=NOW)
    texts = [q.text for q in merged.questions]
    assert "Stale baseline wording" not in texts
    assert "Why this role?" in texts
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_interview_kit_assembly.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'recruiter.pipeline.interview_kit'`

- [ ] **Step 3: Write the implementation**

```python
# src/recruiter/pipeline/interview_kit.py
"""Assembling a kit from a job baseline and generated probes.

Pure functions: no database, no LLM. The two rules that matter most in the
feature live here, so they can be tested without either.
"""
import uuid

from recruiter.schemas.interview import BaselineQuestion, InterviewKit, KitQuestion


def _probe_questions(probes: list[str], criteria_by_probe: list[str | None]) -> list[KitQuestion]:
    return [
        KitQuestion(
            id=f"p-{uuid.uuid4().hex[:8]}",
            text=text,
            source="probe",
            criterion=criteria_by_probe[i] if i < len(criteria_by_probe) else None,
        )
        for i, text in enumerate(probes)
    ]


def _baseline_questions(baseline: list[BaselineQuestion]) -> list[KitQuestion]:
    return [
        KitQuestion(id=f"b-{b.id}", text=b.text, source="baseline", criterion=b.criterion)
        for b in baseline
    ]


def build_kit(
    baseline: list[BaselineQuestion],
    probes: list[str],
    *,
    criteria_by_probe: list[str | None],
    now: str,
) -> InterviewKit:
    """Snapshot the baseline, then append the generated probes."""
    return InterviewKit(
        status="ready",
        generated_at=now,
        questions=_baseline_questions(baseline) + _probe_questions(probes, criteria_by_probe),
    )


def merge_regenerated(
    existing: InterviewKit,
    baseline: list[BaselineQuestion],
    probes: list[str],
    *,
    criteria_by_probe: list[str | None],
    now: str,
) -> InterviewKit:
    """Regenerate, keeping every question that already has an answer.

    Answered questions are evidence of what was actually asked and said, so
    they survive regeneration verbatim — including their rating and their
    original wording. Only unanswered questions are replaced: baseline ones
    re-snapshot from the job's current baseline, probes are regenerated.
    """
    answered = [q for q in existing.questions if q.answer is not None]
    answered_baseline_ids = {q.id for q in answered if q.source == "baseline"}

    fresh_baseline = [
        q for q in _baseline_questions(baseline) if q.id not in answered_baseline_ids
    ]
    return InterviewKit(
        status="ready",
        generated_at=now,
        submitted_at=existing.submitted_at,
        questions=answered + fresh_baseline + _probe_questions(probes, criteria_by_probe),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_interview_kit_assembly.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/pipeline/interview_kit.py tests/unit/test_interview_kit_assembly.py
git commit -m "feat(interview): kit assembly with answer-preserving regeneration"
```

---

### Task 3: The generator — probes from score rationales

**Files:**
- Create: `src/recruiter/pipeline/interview_kit_generator.py`
- Modify: `src/recruiter/schemas/interview.py` (add the LLM output schema)
- Test: `tests/unit/test_interview_kit_generator.py`

**Interfaces:**
- Consumes: `LLMClient`, `LLMMessage` from `recruiter.llm.client`; `FakeLLMClient` for tests.
- Produces: `generate_probes(*, profile: str, criteria: list[CriteriaItem], score_breakdown: list[dict] | None, baseline: list[BaselineQuestion], llm: LLMClient) -> GeneratedQuestions`; schemas `GeneratedQuestion(text, criterion)` and `GeneratedQuestions(questions)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_interview_kit_generator.py
import pytest

from recruiter.llm.client import FakeLLMClient
from recruiter.pipeline.interview_kit_generator import generate_probes
from recruiter.schemas.interview import BaselineQuestion, GeneratedQuestion, GeneratedQuestions
from recruiter.schemas.job import CriteriaItem


@pytest.mark.asyncio
async def test_prompt_carries_the_score_rationales() -> None:
    """The rationales are the point: they already name the doubt to probe."""
    llm = FakeLLMClient(structured_responses=[
        GeneratedQuestions(questions=[GeneratedQuestion(text="Probe?", criterion="Kubernetes")]),
    ])
    await generate_probes(
        profile="Ingénieur DevOps, 2 ans",
        criteria=[CriteriaItem(name="Kubernetes", weight=20, description="prod clusters")],
        score_breakdown=[{"criterion": "Kubernetes", "score": 60,
                          "rationale": "no evidence of production-grade clusters"}],
        baseline=[BaselineQuestion(id="b1", text="Why this role?")],
        llm=llm,
    )
    prompt = llm.calls[0]["messages"][0].content
    assert "no evidence of production-grade clusters" in prompt
    assert "Why this role?" in prompt, "baseline must be shown so probes don't duplicate it"


@pytest.mark.asyncio
async def test_uses_a_budget_large_enough_for_a_reasoning_model() -> None:
    """512 is what made query suggestion fail with null content (PR #17)."""
    llm = FakeLLMClient(structured_responses=[GeneratedQuestions(questions=[])])
    await generate_probes(profile="p", criteria=[], score_breakdown=None, baseline=[], llm=llm)
    assert llm.calls[0]["max_tokens"] >= 2048


@pytest.mark.asyncio
async def test_returns_the_generated_questions() -> None:
    llm = FakeLLMClient(structured_responses=[
        GeneratedQuestions(questions=[GeneratedQuestion(text="A?", criterion=None)]),
    ])
    out = await generate_probes(profile="p", criteria=[], score_breakdown=None,
                                baseline=[], llm=llm)
    assert [q.text for q in out.questions] == ["A?"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_interview_kit_generator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'recruiter.pipeline.interview_kit_generator'`

- [ ] **Step 3: Add the LLM output schema**

```python
# src/recruiter/schemas/interview.py — append
class GeneratedQuestion(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    criterion: str | None = Field(default=None, max_length=200)


class GeneratedQuestions(BaseModel):
    questions: list[GeneratedQuestion] = Field(default_factory=list)
```

- [ ] **Step 4: Write the generator**

```python
# src/recruiter/pipeline/interview_kit_generator.py
"""Interview probes generated from what scoring already doubted.

The scorer writes a rationale per criterion — "Docker/Kubernetes listed, but
no clear evidence of managing production-grade clusters". That sentence is
already the question worth asking; this turns it into one.
"""
from recruiter.llm.client import LLMClient, LLMMessage
from recruiter.schemas.interview import BaselineQuestion, GeneratedQuestions
from recruiter.schemas.job import CriteriaItem

_SYSTEM = (
    "You write interview questions for a technical recruiter. "
    "Each question probes a specific doubt about this candidate — never generic "
    "filler, never a question the CV already answers. Prefer asking for a concrete "
    "story over asking whether they know a technology. Return 3-6 questions."
)


def _build_prompt(
    *,
    profile: str,
    criteria: list[CriteriaItem],
    score_breakdown: list[dict] | None,
    baseline: list[BaselineQuestion],
) -> str:
    parts = [f"Candidate profile:\n{profile}\n"]
    if criteria:
        parts.append("Weighted criteria:\n" + "\n".join(
            f"- {c.name} (weight {c.weight}): {c.description}" for c in criteria
        ) + "\n")
    if score_breakdown:
        parts.append("Scoring found these specific doubts:\n" + "\n".join(
            f"- {row.get('criterion')} scored {row.get('score')}: {row.get('rationale')}"
            for row in score_breakdown
        ) + "\n")
    if baseline:
        parts.append(
            "These questions are already being asked — do NOT duplicate them:\n"
            + "\n".join(f"- {b.text}" for b in baseline) + "\n"
        )
    parts.append("Return JSON with a `questions` array of {text, criterion}.")
    return "\n".join(parts)


async def generate_probes(
    *,
    profile: str,
    criteria: list[CriteriaItem],
    score_breakdown: list[dict] | None,
    baseline: list[BaselineQuestion],
    llm: LLMClient,
) -> GeneratedQuestions:
    prompt = _build_prompt(
        profile=profile, criteria=criteria,
        score_breakdown=score_breakdown, baseline=baseline,
    )
    return await llm.chat_structured(
        messages=[LLMMessage(role="user", content=prompt)],
        schema=GeneratedQuestions,
        system=_SYSTEM,
        # 2048, not 512: reasoning tokens count against this budget (PR #17).
        max_tokens=2048,
        temperature=0.3,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_interview_kit_generator.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add src/recruiter/pipeline/interview_kit_generator.py src/recruiter/schemas/interview.py \
        tests/unit/test_interview_kit_generator.py
git commit -m "feat(interview): generate probes from score rationales"
```

---

### Task 4: Read and generate endpoints

**Files:**
- Create: `src/recruiter/api/interview.py`
- Modify: `src/recruiter/main.py` (register the router)
- Test: `tests/api/test_interview_api.py`

**Interfaces:**
- Consumes: `build_kit`, `merge_regenerated` (Task 2), `generate_probes` (Task 3), `InterviewKit` (Task 1).
- Produces: `run_generate_kit(*, application_id: int, engine: AsyncEngine, llm: LLMClient, bus: EventBus) -> None`; routes `GET /api/applications/{id}/interview-kit` and `POST /api/applications/{id}/interview-kit/generate`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_interview_api.py
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_returns_null_kit_before_generation(api_client: AsyncClient) -> None:
    app_id = await _create_scored_app(api_client)
    resp = await api_client.get(f"/api/applications/{app_id}/interview-kit")
    assert resp.status_code == 200
    assert resp.json()["kit"] is None


@pytest.mark.asyncio
async def test_generate_returns_202_and_marks_generating(api_client: AsyncClient) -> None:
    """202 because the model call runs in the background — the request must
    not block on it, and must not fail because of it."""
    app_id = await _create_scored_app(api_client)
    resp = await api_client.post(f"/api/applications/{app_id}/interview-kit/generate")
    assert resp.status_code == 202
    kit = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()["kit"]
    assert kit["status"] == "generating"


@pytest.mark.asyncio
async def test_generate_404s_for_an_unknown_application(api_client: AsyncClient) -> None:
    resp = await api_client.post("/api/applications/999999/interview-kit/generate")
    assert resp.status_code == 404
```

`_create_scored_app` already exists in `tests/api/test_chat_search_tool.py`; move it to `tests/api/conftest.py` as a shared fixture-helper and import it in both places rather than duplicating it.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_interview_api.py -v`
Expected: FAIL with 404 on every route (router not registered)

- [ ] **Step 3: Write the router**

```python
# src/recruiter/api/interview.py
"""Interview kit endpoints.

Generation runs in a background task deliberately: the stage transition that
triggers it must be durable before any model is called, so a failed
generation can never leave a candidate stuck between stages.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from pydantic import BaseModel

from recruiter.api.candidates import get_engine_dep, get_llm
from recruiter.api.deps import get_session, require_role
from recruiter.events import EventBus, get_event_bus
from recruiter.llm.client import LLMClient
from recruiter.models import Application, Candidate, Job, Role, User
from recruiter.pipeline.interview_kit import build_kit, merge_regenerated
from recruiter.pipeline.interview_kit_generator import generate_probes
from recruiter.schemas.interview import BaselineQuestion, InterviewKit
from recruiter.schemas.job import CriteriaItem

router = APIRouter(prefix="/api", tags=["interview"])
logger = logging.getLogger(__name__)


class InterviewKitRead(BaseModel):
    kit: InterviewKit | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/applications/{application_id}/interview-kit", response_model=InterviewKitRead)
async def get_kit(
    application_id: int,
    session: AsyncSession = Depends(get_session),
) -> InterviewKitRead:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    raw = app_row.interview_kit
    return InterviewKitRead(kit=InterviewKit.model_validate(raw) if raw else None)


async def run_generate_kit(
    *, application_id: int, engine: AsyncEngine, llm: LLMClient, bus: EventBus,
) -> None:
    """Generate probes and store the assembled kit. Never raises."""
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        app_row = await session.get(Application, application_id)
        if app_row is None:
            return
        job = await session.get(Job, app_row.job_id)
        candidate = await session.get(Candidate, app_row.candidate_id)
        baseline = [BaselineQuestion.model_validate(b)
                    for b in (job.interview_baseline or [])]
        try:
            generated = await generate_probes(
                profile=candidate.summary or candidate.full_name or "",
                criteria=[CriteriaItem.model_validate(c) for c in (job.criteria or [])],
                score_breakdown=app_row.score_breakdown,
                baseline=baseline,
                llm=llm,
            )
            texts = [q.text for q in generated.questions]
            criteria_by_probe = [q.criterion for q in generated.questions]
            existing_raw = app_row.interview_kit or {}
            existing_questions = existing_raw.get("questions") or []
            if existing_questions:
                kit = merge_regenerated(
                    InterviewKit.model_validate(existing_raw), baseline, texts,
                    criteria_by_probe=criteria_by_probe, now=_now(),
                )
            else:
                kit = build_kit(baseline, texts,
                                criteria_by_probe=criteria_by_probe, now=_now())
        except Exception as exc:  # noqa: BLE001 — recorded, not swallowed
            logger.warning("interview kit generation failed: %s", exc, exc_info=True)
            kit = InterviewKit(status="error", error=str(exc)[:500])
        app_row.interview_kit = kit.model_dump()
        await session.commit()
    await bus.publish({
        "type": "interview_kit", "application_id": application_id, "status": kit.status,
    })


@router.post("/applications/{application_id}/interview-kit/generate", status_code=202)
async def generate_kit(
    application_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    engine: AsyncEngine = Depends(get_engine_dep),
    llm: LLMClient = Depends(get_llm),
    bus: EventBus = Depends(get_event_bus),
    _: User = Depends(require_role(Role.RECRUITER)),
) -> dict:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")

    existing = app_row.interview_kit or {}
    app_row.interview_kit = {**existing, "status": "generating", "error": None,
                             "questions": existing.get("questions") or []}
    await session.commit()

    background_tasks.add_task(
        run_generate_kit, application_id=application_id, engine=engine, llm=llm, bus=bus,
    )
    return {"application_id": application_id}
```

- [ ] **Step 4: Register the router**

```python
# src/recruiter/main.py — beside the other include_router calls
from recruiter.api import interview
app.include_router(interview.router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/api/test_interview_api.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add src/recruiter/api/interview.py src/recruiter/main.py tests/api/test_interview_api.py \
        tests/api/conftest.py
git commit -m "feat(interview): read and generate endpoints"
```

---

### Task 5: PATCH — edits, answers, ratings

**Files:**
- Modify: `src/recruiter/api/interview.py`
- Test: `tests/api/test_interview_api.py`

**Interfaces:**
- Consumes: `InterviewKit`, `KitQuestion` (Task 1); the router from Task 4.
- Produces: `PATCH /api/applications/{id}/interview-kit` taking `{"questions": [KitQuestion, ...]}` and returning the stored `InterviewKitRead`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_interview_api.py — append
@pytest.mark.asyncio
async def test_patch_stores_answers_and_ratings(api_client: AsyncClient) -> None:
    app_id = await _create_scored_app(api_client)
    await api_client.post(f"/api/applications/{app_id}/interview-kit/generate")

    body = {"questions": [
        {"id": "q1", "text": "Describe an incident.", "source": "probe",
         "answer": "Handled an etcd outage", "rating": "strong"},
    ]}
    resp = await api_client.patch(f"/api/applications/{app_id}/interview-kit", json=body)
    assert resp.status_code == 200
    q = resp.json()["kit"]["questions"][0]
    assert q["answer"] == "Handled an etcd outage"
    assert q["rating"] == "strong"


@pytest.mark.asyncio
async def test_patch_rejects_duplicate_question_ids(api_client: AsyncClient) -> None:
    """Ids address questions; duplicates make an edit ambiguous."""
    app_id = await _create_scored_app(api_client)
    await api_client.post(f"/api/applications/{app_id}/interview-kit/generate")
    body = {"questions": [
        {"id": "same", "text": "One", "source": "probe"},
        {"id": "same", "text": "Two", "source": "probe"},
    ]}
    resp = await api_client.patch(f"/api/applications/{app_id}/interview-kit", json=body)
    assert resp.status_code == 422
    assert "duplicate" in resp.text.lower()


@pytest.mark.asyncio
async def test_patch_404s_when_no_kit_exists(api_client: AsyncClient) -> None:
    app_id = await _create_scored_app(api_client)
    resp = await api_client.patch(f"/api/applications/{app_id}/interview-kit",
                                  json={"questions": []})
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_interview_api.py -k patch -v`
Expected: FAIL with 405 Method Not Allowed

- [ ] **Step 3: Write the implementation**

```python
# src/recruiter/api/interview.py — append
class InterviewKitPatch(BaseModel):
    questions: list[KitQuestion]


@router.patch("/applications/{application_id}/interview-kit",
              response_model=InterviewKitRead)
async def patch_kit(
    application_id: int,
    payload: InterviewKitPatch,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(Role.RECRUITER)),
) -> InterviewKitRead:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    if not app_row.interview_kit:
        raise HTTPException(status_code=404, detail="no interview kit; generate one first")

    ids = [q.id for q in payload.questions]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="duplicate question ids")

    kit = InterviewKit.model_validate(app_row.interview_kit)
    kit.questions = payload.questions
    app_row.interview_kit = kit.model_dump()
    await session.commit()
    return InterviewKitRead(kit=kit)
```

Add `KitQuestion` to the existing `recruiter.schemas.interview` import at the top of the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/api/test_interview_api.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/api/interview.py tests/api/test_interview_api.py
git commit -m "feat(interview): patch kit questions, answers and ratings"
```

---

### Task 6: Submit — record, and advance the stage once

**Files:**
- Modify: `src/recruiter/api/interview.py`
- Test: `tests/api/test_interview_submit.py`

**Interfaces:**
- Consumes: the router and `InterviewKitRead` from Task 4.
- Produces: `POST /api/applications/{id}/interview-kit/submit` returning `InterviewKitRead`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_interview_submit.py
import pytest
from httpx import AsyncClient

from tests.api.conftest import _create_scored_app


async def _kit_ready(api_client: AsyncClient, app_id: int) -> None:
    await api_client.post(f"/api/applications/{app_id}/interview-kit/generate")
    await api_client.patch(f"/api/applications/{app_id}/interview-kit", json={
        "questions": [{"id": "q1", "text": "Q?", "source": "probe", "answer": "A"}],
    })


@pytest.mark.asyncio
async def test_submit_advances_scheduled_to_interviewed(api_client: AsyncClient) -> None:
    app_id = await _create_scored_app(api_client)
    for stage in ("validated", "invited", "scheduled"):
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": stage})
    await _kit_ready(api_client, app_id)

    resp = await api_client.post(f"/api/applications/{app_id}/interview-kit/submit")
    assert resp.status_code == 200
    assert resp.json()["kit"]["submitted_at"] is not None
    app = (await api_client.get(f"/api/applications/{app_id}")).json()
    assert app["stage"] == "interviewed"


@pytest.mark.asyncio
async def test_submitting_again_does_not_advance_further(api_client: AsyncClient) -> None:
    """Editing and re-submitting after the interview must be safe."""
    app_id = await _create_scored_app(api_client)
    for stage in ("validated", "invited", "scheduled"):
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": stage})
    await _kit_ready(api_client, app_id)

    await api_client.post(f"/api/applications/{app_id}/interview-kit/submit")
    await api_client.post(f"/api/applications/{app_id}/interview-kit/submit")

    app = (await api_client.get(f"/api/applications/{app_id}")).json()
    assert app["stage"] == "interviewed"


@pytest.mark.asyncio
async def test_submit_with_unanswered_questions_is_allowed(api_client: AsyncClient) -> None:
    """Real interviews get cut short; blocking would encourage invented answers."""
    app_id = await _create_scored_app(api_client)
    for stage in ("validated", "invited", "scheduled"):
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": stage})
    await api_client.post(f"/api/applications/{app_id}/interview-kit/generate")
    await api_client.patch(f"/api/applications/{app_id}/interview-kit", json={
        "questions": [{"id": "q1", "text": "Q?", "source": "probe", "answer": None}],
    })

    resp = await api_client.post(f"/api/applications/{app_id}/interview-kit/submit")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_interview_submit.py -v`
Expected: FAIL with 404 (route missing)

- [ ] **Step 3: Write the implementation**

```python
# src/recruiter/api/interview.py — append
@router.post("/applications/{application_id}/interview-kit/submit",
             response_model=InterviewKitRead)
async def submit_kit(
    application_id: int,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(Role.RECRUITER)),
) -> InterviewKitRead:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    if not app_row.interview_kit:
        raise HTTPException(status_code=404, detail="no interview kit; generate one first")

    kit = InterviewKit.model_validate(app_row.interview_kit)
    kit.submitted_at = _now()
    app_row.interview_kit = kit.model_dump()

    # Advance only from SCHEDULED. Already interviewed or beyond means this is
    # an edit to a past interview, not a new one — re-submitting must not
    # push the candidate further down the pipeline.
    if app_row.stage == Stage.SCHEDULED:
        app_row.stage = Stage.INTERVIEWED
        app_row.interviewed_at = datetime.now(timezone.utc)

    await session.commit()
    return InterviewKitRead(kit=kit)
```

Add `Stage` to the `recruiter.models` import at the top of the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/api/test_interview_submit.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/api/interview.py tests/api/test_interview_submit.py
git commit -m "feat(interview): submit records the kit and advances the stage once"
```

---

### Task 7: Auto-generate on entering Scheduled

The constraint this task exists to protect: a generation failure must leave the candidate correctly in `SCHEDULED`.

**Files:**
- Modify: `src/recruiter/api/applications.py:320-341` (the stage transition block)
- Test: `tests/api/test_interview_stage_wiring.py`

**Interfaces:**
- Consumes: `run_generate_kit` from Task 4.
- Produces: no new symbols; `PATCH /api/applications/{id}` with `stage: "scheduled"` now enqueues generation.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_interview_stage_wiring.py
import pytest
from httpx import AsyncClient

from tests.api.conftest import _create_scored_app


@pytest.mark.asyncio
async def test_moving_to_scheduled_starts_a_kit(api_client: AsyncClient) -> None:
    app_id = await _create_scored_app(api_client)
    for stage in ("validated", "invited"):
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": stage})

    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})

    kit = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()["kit"]
    assert kit is not None
    assert kit["status"] in ("generating", "ready", "error")


@pytest.mark.asyncio
async def test_a_failing_generation_still_leaves_the_candidate_scheduled(
    api_client: AsyncClient, monkeypatch,
) -> None:
    """The whole background-task design exists for this. An LLM outage must
    never strand a candidate between stages."""
    from recruiter.api import interview

    async def boom(**kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(interview, "generate_probes", boom)

    app_id = await _create_scored_app(api_client)
    for stage in ("validated", "invited"):
        await api_client.patch(f"/api/applications/{app_id}", json={"stage": stage})

    resp = await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})
    assert resp.status_code == 200

    app = (await api_client.get(f"/api/applications/{app_id}")).json()
    assert app["stage"] == "scheduled", "a failed kit must not affect the stage"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_interview_stage_wiring.py -v`
Expected: FAIL — the first test finds `kit is None`

- [ ] **Step 3: Write the implementation**

In `patch_application`, add the dependencies to the signature:

```python
async def patch_application(
    application_id: int,
    payload: ApplicationUpdate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    engine: AsyncEngine = Depends(get_engine_dep),
    llm: LLMClient = Depends(get_llm),
    bus: EventBus = Depends(get_event_bus),
) -> ApplicationRead:
```

Then, inside the transition block, replace the `SCHEDULED` branch:

```python
        elif new_stage == Stage.SCHEDULED:
            app_row.scheduled_at = now
            # Mark the kit pending here, but enqueue the model call for AFTER
            # the commit below. The transition must be durable before anything
            # that can fail runs — a stuck stage is far worse than a missing kit.
            app_row.interview_kit = {"status": "generating", "error": None,
                                     "questions": []}
            schedule_kit_generation = True
```

Initialise `schedule_kit_generation = False` before the transition block, and after the existing `await session.commit()` add:

```python
    if schedule_kit_generation:
        background_tasks.add_task(
            run_generate_kit,
            application_id=application_id, engine=engine, llm=llm, bus=bus,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/api/test_interview_stage_wiring.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the whole backend suite — this task touches a shared endpoint**

Run: `uv run pytest -q`
Expected: all pass. `PATCH /applications/{id}` is used by the kanban, the action bar and the e2e suite; a regression here is a regression everywhere.

- [ ] **Step 6: Commit**

```bash
git add src/recruiter/api/applications.py tests/api/test_interview_stage_wiring.py
git commit -m "feat(interview): generate a kit when a candidate is scheduled"
```

---

### Task 8: The job baseline endpoint

**Files:**
- Modify: `src/recruiter/api/jobs.py`, `src/recruiter/schemas/job.py`
- Test: `tests/api/test_interview_baseline_api.py`

**Interfaces:**
- Consumes: `BaselineQuestion` (Task 1).
- Produces: `PUT /api/jobs/{id}/interview-baseline` taking `{"questions": [BaselineQuestion, ...]}`; `JobRead.interview_baseline`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_interview_baseline_api.py
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_put_and_read_back_the_baseline(api_client: AsyncClient) -> None:
    job = (await api_client.post("/api/jobs", json={
        "title": "SRE", "description": "d", "criteria": [],
    })).json()
    body = {"questions": [{"id": "b1", "text": "Why this role?"}]}

    resp = await api_client.put(f"/api/jobs/{job['id']}/interview-baseline", json=body)
    assert resp.status_code == 200

    read = (await api_client.get(f"/api/jobs/{job['id']}")).json()
    assert read["interview_baseline"][0]["text"] == "Why this role?"


@pytest.mark.asyncio
async def test_baseline_rejects_duplicate_ids(api_client: AsyncClient) -> None:
    job = (await api_client.post("/api/jobs", json={
        "title": "SRE", "description": "d", "criteria": [],
    })).json()
    body = {"questions": [{"id": "b1", "text": "One"}, {"id": "b1", "text": "Two"}]}
    resp = await api_client.put(f"/api/jobs/{job['id']}/interview-baseline", json=body)
    assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_interview_baseline_api.py -v`
Expected: FAIL with 405 / KeyError on `interview_baseline`

- [ ] **Step 3: Write the implementation**

```python
# src/recruiter/schemas/job.py — add to JobRead
    interview_baseline: list[dict] | None = None
```

```python
# src/recruiter/api/jobs.py — append
from recruiter.schemas.interview import BaselineQuestion


class InterviewBaselineUpdate(BaseModel):
    questions: list[BaselineQuestion]


@router.put("/{job_id}/interview-baseline", response_model=JobRead)
async def put_interview_baseline(
    job_id: int,
    payload: InterviewBaselineUpdate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(Role.RECRUITER)),
) -> JobRead:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    ids = [q.id for q in payload.questions]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="duplicate question ids")

    job.interview_baseline = [q.model_dump() for q in payload.questions]
    await session.commit()
    await session.refresh(job)
    return _to_job_read(job)
```

Then add the field to the job read construction, next to `criteria`:

```python
    return JobRead(
        # ...existing fields unchanged...
        interview_baseline=job.interview_baseline,
    )
```

If `jobs.py` builds `JobRead` inline in more than one endpoint rather than
through a helper, add the field at each site — `GET /jobs/{id}` is the one
this feature depends on.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/api/test_interview_baseline_api.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/api/jobs.py src/recruiter/schemas/job.py \
        tests/api/test_interview_baseline_api.py
git commit -m "feat(interview): per-job baseline questions endpoint"
```

---

### Task 9: Frontend data hook

**Files:**
- Create: `recruiter-frontend/src/hooks/use-interview-kit.ts`
- Modify: `recruiter-frontend/src/lib/query-keys.ts`
- Test: `recruiter-frontend/src/hooks/use-interview-kit.test.tsx`

**Interfaces:**
- Consumes: the endpoints from Tasks 4–6.
- Produces: `useInterviewKit(applicationId: number)` returning `{ kit, isLoading, generate, patch, submit }`; types `KitQuestion`, `InterviewKit`, `Rating`.

- [ ] **Step 1: Write the failing test**

```tsx
// recruiter-frontend/src/hooks/use-interview-kit.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { useInterviewKit } from "./use-interview-kit";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function wrap() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("useInterviewKit", () => {
  it("loads the kit", async () => {
    server.use(
      http.get("http://localhost:8000/api/applications/1/interview-kit", () =>
        HttpResponse.json({ kit: { status: "ready", questions: [
          { id: "q1", text: "Q?", source: "probe", answer: null, rating: null },
        ] } }),
      ),
    );
    const { result } = renderHook(() => useInterviewKit(1), { wrapper: wrap() });
    await waitFor(() => expect(result.current.kit?.questions).toHaveLength(1));
    expect(result.current.kit?.status).toBe("ready");
  });

  it("reports a null kit as absent rather than erroring", async () => {
    server.use(
      http.get("http://localhost:8000/api/applications/1/interview-kit", () =>
        HttpResponse.json({ kit: null }),
      ),
    );
    const { result } = renderHook(() => useInterviewKit(1), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.kit).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd recruiter-frontend && npx vitest --run src/hooks/use-interview-kit.test.tsx`
Expected: FAIL — cannot resolve `./use-interview-kit`

- [ ] **Step 3: Write the hook**

```ts
// recruiter-frontend/src/hooks/use-interview-kit.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

export type Rating = "strong" | "adequate" | "weak";

export interface KitQuestion {
  id: string;
  text: string;
  source: "baseline" | "probe";
  criterion?: string | null;
  answer: string | null;
  rating: Rating | null;
}

export interface InterviewKit {
  status: "generating" | "ready" | "error";
  error?: string | null;
  generated_at?: string | null;
  submitted_at?: string | null;
  questions: KitQuestion[];
}

export function useInterviewKit(applicationId: number) {
  const qc = useQueryClient();
  const key = queryKeys.interviewKit(applicationId);
  const path = `/api/applications/${applicationId}/interview-kit`;

  const query = useQuery({
    queryKey: key,
    queryFn: () => api<{ kit: InterviewKit | null }>(path),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: key });

  const generate = useMutation({
    mutationFn: () => api(`${path}/generate`, { method: "POST" }),
    onSuccess: invalidate,
  });

  const patch = useMutation({
    mutationFn: (questions: KitQuestion[]) =>
      api(path, { method: "PATCH", body: JSON.stringify({ questions }) }),
    onSuccess: invalidate,
  });

  const submit = useMutation({
    mutationFn: () => api(`${path}/submit`, { method: "POST" }),
    onSuccess: () => {
      invalidate();
      // The stage changed, so the kanban and the detail header are stale too.
      qc.invalidateQueries({ queryKey: queryKeys.application(applicationId) });
    },
  });

  return {
    kit: query.data?.kit ?? null,
    isLoading: query.isLoading,
    generate,
    patch,
    submit,
  };
}
```

```ts
// recruiter-frontend/src/lib/query-keys.ts — add
  interviewKit: (applicationId: number) => ["interview-kit", applicationId] as const,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest --run src/hooks/use-interview-kit.test.tsx`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add recruiter-frontend/src/hooks/use-interview-kit.ts \
        recruiter-frontend/src/hooks/use-interview-kit.test.tsx \
        recruiter-frontend/src/lib/query-keys.ts
git commit -m "feat(interview): frontend hook for the interview kit"
```

---

### Task 10: The interview kit panel

**Files:**
- Create: `recruiter-frontend/src/components/candidate/interview-kit-section.tsx`
- Modify: `recruiter-frontend/src/routes/application-detail.tsx`
- Test: `recruiter-frontend/src/components/candidate/interview-kit-section.test.tsx`

**Interfaces:**
- Consumes: `useInterviewKit`, `KitQuestion`, `Rating` (Task 9).
- Produces: `<InterviewKitSection applicationId={number} canWrite={boolean} />`.

- [ ] **Step 1: Write the failing test**

```tsx
// recruiter-frontend/src/components/candidate/interview-kit-section.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { InterviewKitSection } from "./interview-kit-section";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function mountWithKit(kit: unknown, capture: { body?: any } = {}) {
  server.use(
    http.get("http://localhost:8000/api/applications/1/interview-kit", () =>
      HttpResponse.json({ kit }),
    ),
    http.patch("http://localhost:8000/api/applications/1/interview-kit", async ({ request }) => {
      capture.body = await request.json();
      return HttpResponse.json({ kit });
    }),
    http.post("http://localhost:8000/api/applications/1/interview-kit/generate", () =>
      HttpResponse.json({ application_id: 1 }, { status: 202 }),
    ),
  );
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return render(<Wrapper><InterviewKitSection applicationId={1} canWrite /></Wrapper>);
}

const READY = {
  status: "ready",
  questions: [
    { id: "b1", text: "Why this role?", source: "baseline", answer: null, rating: null },
    { id: "p1", text: "Describe an incident.", source: "probe",
      criterion: "Kubernetes", answer: null, rating: null },
  ],
};

describe("InterviewKitSection", () => {
  it("offers Generate when there is no kit", async () => {
    mountWithKit(null);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /generate interview kit/i })).toBeInTheDocument(),
    );
  });

  it("shows a loader while generating", async () => {
    mountWithKit({ status: "generating", questions: [] });
    await waitFor(() => expect(screen.getByText(/generating/i)).toBeInTheDocument());
  });

  it("shows the error and a retry when generation failed", async () => {
    mountWithKit({ status: "error", error: "model unavailable", questions: [] });
    await waitFor(() => expect(screen.getByText(/model unavailable/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("renders questions with their source badge", async () => {
    mountWithKit(READY);
    await waitFor(() => expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());
    expect(screen.getByText(/^Role$/)).toBeInTheDocument();
    expect(screen.getByText(/for this candidate/i)).toBeInTheDocument();
  });

  it("saves a typed answer", async () => {
    const cap: { body?: any } = {};
    mountWithKit(READY, cap);
    await waitFor(() => expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());

    await userEvent.type(screen.getAllByPlaceholderText(/what they said/i)[0], "Wants scale");
    await userEvent.click(screen.getByRole("button", { name: /save answers/i }));

    await waitFor(() => expect(cap.body).toBeDefined());
    expect(cap.body.questions[0].answer).toBe("Wants scale");
  });

  it("adds a question and includes it when saving", async () => {
    const cap: { body?: any } = {};
    mountWithKit(READY, cap);
    await waitFor(() => expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: /add question/i }));
    const inputs = screen.getAllByLabelText(/^Question:/i);
    await userEvent.type(inputs[inputs.length - 1], "Anything to ask us?");
    await userEvent.click(screen.getByRole("button", { name: /save answers/i }));

    await waitFor(() => expect(cap.body).toBeDefined());
    expect(cap.body.questions.map((q: any) => q.text)).toContain("Anything to ask us?");
  });

  it("removes a question", async () => {
    const cap: { body?: any } = {};
    mountWithKit(READY, cap);
    await waitFor(() => expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: /remove question: why this role/i }));
    await userEvent.click(screen.getByRole("button", { name: /save answers/i }));

    await waitFor(() => expect(cap.body).toBeDefined());
    expect(cap.body.questions.map((q: any) => q.text)).not.toContain("Why this role?");
  });

  it("hides every write control for a viewer", async () => {
    server.use(
      http.get("http://localhost:8000/api/applications/1/interview-kit", () =>
        HttpResponse.json({ kit: READY }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <InterviewKitSection applicationId={1} canWrite={false} />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByText("Why this role?")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /save answers/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /submit interview/i })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest --run src/components/candidate/interview-kit-section.test.tsx`
Expected: FAIL — cannot resolve `./interview-kit-section`

- [ ] **Step 3: Write the component**

```tsx
// recruiter-frontend/src/components/candidate/interview-kit-section.tsx
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  type KitQuestion, type Rating, useInterviewKit,
} from "@/hooks/use-interview-kit";

const RATINGS: Rating[] = ["strong", "adequate", "weak"];

interface Props {
  applicationId: number;
  canWrite: boolean;
}

export function InterviewKitSection({ applicationId, canWrite }: Props) {
  const { kit, isLoading, generate, patch, submit } = useInterviewKit(applicationId);
  const [draft, setDraft] = useState<KitQuestion[]>([]);

  // The server is the source of truth; local edits are a draft until saved.
  useEffect(() => {
    if (kit?.questions) setDraft(kit.questions);
  }, [kit?.generated_at, kit?.status]);

  if (isLoading) return null;

  if (!kit) {
    return (
      <section className="space-y-2">
        <h3 className="text-lg font-semibold">Interview kit</h3>
        {canWrite && (
          <Button onClick={() => generate.mutate()} disabled={generate.isPending}>
            Generate interview kit
          </Button>
        )}
      </section>
    );
  }

  if (kit.status === "generating") {
    return (
      <section className="space-y-2">
        <h3 className="text-lg font-semibold">Interview kit</h3>
        <p className="text-xs text-muted-foreground animate-pulse">Generating questions…</p>
      </section>
    );
  }

  if (kit.status === "error") {
    return (
      <section className="space-y-2">
        <h3 className="text-lg font-semibold">Interview kit</h3>
        <p className="text-xs border border-yellow-400 bg-yellow-50 text-yellow-900 rounded p-2">
          {kit.error ?? "Generation failed."}
        </p>
        {canWrite && (
          <Button variant="outline" onClick={() => generate.mutate()}>Retry</Button>
        )}
      </section>
    );
  }

  const update = (id: string, patchFields: Partial<KitQuestion>) =>
    setDraft((qs) => qs.map((q) => (q.id === id ? { ...q, ...patchFields } : q)));

  const unanswered = draft.filter((q) => !q.answer?.trim()).length;

  function onSubmit() {
    if (unanswered > 0 &&
        !window.confirm(`${unanswered} question(s) have no answer. Submit anyway?`)) {
      return;
    }
    patch.mutate(draft, {
      onSuccess: () => submit.mutate(undefined, {
        onSuccess: () => toast.success("Interview recorded"),
      }),
    });
  }

  return (
    <section className="space-y-3">
      <h3 className="text-lg font-semibold">Interview kit</h3>
      <ul className="space-y-3">
        {draft.map((q) => (
          <li key={q.id} className="border border-border rounded p-2 space-y-2">
            <div className="flex items-start justify-between gap-2">
              {canWrite ? (
                <input
                  aria-label={`Question: ${q.text}`}
                  className="flex-1 bg-transparent text-sm outline-none"
                  value={q.text}
                  onChange={(e) => update(q.id, { text: e.target.value })}
                />
              ) : (
                <p className="flex-1 text-sm">{q.text}</p>
              )}
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                {q.source === "baseline" ? "Role" : "For this candidate"}
              </span>
              {canWrite && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-auto px-2 py-1 text-xs"
                  aria-label={`Remove question: ${q.text}`}
                  onClick={() => setDraft((qs) => qs.filter((x) => x.id !== q.id))}
                >
                  Remove
                </Button>
              )}
            </div>
            {canWrite ? (
              <Textarea
                placeholder="What they said…"
                value={q.answer ?? ""}
                onChange={(e) => update(q.id, { answer: e.target.value })}
              />
            ) : (
              q.answer && <p className="text-xs text-muted-foreground">{q.answer}</p>
            )}
            {canWrite && (
              <div className="flex gap-1">
                {RATINGS.map((r) => (
                  <Button
                    key={r}
                    type="button"
                    size="sm"
                    variant={q.rating === r ? "default" : "outline"}
                    className="h-auto px-2 py-1 text-xs capitalize"
                    onClick={() => update(q.id, { rating: q.rating === r ? null : r })}
                  >
                    {r}
                  </Button>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
      {canWrite && (
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() =>
              setDraft((qs) => [...qs, {
                id: `m-${Date.now()}`, text: "", source: "probe",
                criterion: null, answer: null, rating: null,
              }])}
          >
            Add question
          </Button>
          <Button variant="outline" onClick={() => patch.mutate(draft)}>Save answers</Button>
          <Button onClick={onSubmit}>Submit interview</Button>
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 4: Render it on the detail page**

In `recruiter-frontend/src/routes/application-detail.tsx`, beside `<EnrichmentSection ... />`:

```tsx
<InterviewKitSection applicationId={appId} canWrite={canWrite} />
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npx vitest --run src/components/candidate/interview-kit-section.test.tsx`
Expected: PASS (6 tests)

- [ ] **Step 6: Typecheck and run the whole frontend suite**

Run: `npm run lint && npx vitest --run`
Expected: `tsc --noEmit` silent; all tests pass

- [ ] **Step 7: Commit**

```bash
git add recruiter-frontend/src/components/candidate/interview-kit-section.tsx \
        recruiter-frontend/src/components/candidate/interview-kit-section.test.tsx \
        recruiter-frontend/src/routes/application-detail.tsx
git commit -m "feat(interview): interview kit panel on the candidate page"
```

---

### Task 11: Editing the job baseline

**Files:**
- Create: `recruiter-frontend/src/components/jobs/edit-interview-baseline-sheet.tsx`
- Modify: `recruiter-frontend/src/routes/job-detail.tsx`
- Test: `recruiter-frontend/src/components/jobs/edit-interview-baseline-sheet.test.tsx`

**Interfaces:**
- Consumes: `PUT /api/jobs/{id}/interview-baseline` (Task 8).
- Produces: `<EditInterviewBaselineSheet jobId={number} open={boolean} onOpenChange={(o: boolean) => void} />`.

Read `recruiter-frontend/src/components/jobs/edit-criteria-sheet.tsx` first and mirror its structure — same sheet, same add/remove row interaction, same save button placement. Do not invent a second vocabulary for the same job.

- [ ] **Step 1: Write the failing test**

```tsx
// recruiter-frontend/src/components/jobs/edit-interview-baseline-sheet.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { EditInterviewBaselineSheet } from "./edit-interview-baseline-sheet";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function mount(capture: { body?: any }) {
  server.use(
    http.get("http://localhost:8000/api/jobs/1", () =>
      HttpResponse.json({ id: 1, title: "SRE", criteria: [],
                          interview_baseline: [{ id: "b1", text: "Why this role?" }] }),
    ),
    http.put("http://localhost:8000/api/jobs/1/interview-baseline", async ({ request }) => {
      capture.body = await request.json();
      return HttpResponse.json({ id: 1, title: "SRE", criteria: [], interview_baseline: [] });
    }),
  );
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return render(
    <Wrapper><EditInterviewBaselineSheet jobId={1} open onOpenChange={() => {}} /></Wrapper>,
  );
}

describe("EditInterviewBaselineSheet", () => {
  it("loads the existing baseline questions", async () => {
    mount({});
    await waitFor(() =>
      expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument(),
    );
  });

  it("adds a question and saves it", async () => {
    const cap: { body?: any } = {};
    mount(cap);
    await waitFor(() =>
      expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByRole("button", { name: /add question/i }));
    const inputs = screen.getAllByLabelText(/baseline question/i);
    await userEvent.type(inputs[inputs.length - 1], "Notice period?");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(cap.body).toBeDefined());
    expect(cap.body.questions.map((q: any) => q.text)).toContain("Notice period?");
  });

  it("does not send a question left blank", async () => {
    const cap: { body?: any } = {};
    mount(cap);
    await waitFor(() =>
      expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByRole("button", { name: /add question/i }));
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(cap.body).toBeDefined());
    expect(cap.body.questions).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest --run src/components/jobs/edit-interview-baseline-sheet.test.tsx`
Expected: FAIL — cannot resolve `./edit-interview-baseline-sheet`

- [ ] **Step 3: Write the sheet**

```tsx
// recruiter-frontend/src/components/jobs/edit-interview-baseline-sheet.tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

interface BaselineQuestion {
  id: string;
  text: string;
}

interface Props {
  jobId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function EditInterviewBaselineSheet({ jobId, open, onOpenChange }: Props) {
  const qc = useQueryClient();
  const job = useQuery({
    queryKey: queryKeys.job(jobId),
    queryFn: () => api<{ interview_baseline: BaselineQuestion[] | null }>(`/api/jobs/${jobId}`),
  });
  const [rows, setRows] = useState<BaselineQuestion[]>([]);

  useEffect(() => {
    if (job.data) setRows(job.data.interview_baseline ?? []);
  }, [job.data]);

  const save = useMutation({
    mutationFn: (questions: BaselineQuestion[]) =>
      api(`/api/jobs/${jobId}/interview-baseline`, {
        method: "PUT", body: JSON.stringify({ questions }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.job(jobId) });
      toast.success("Baseline questions saved");
      onOpenChange(false);
    },
  });

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="space-y-3">
        <SheetHeader><SheetTitle>Baseline interview questions</SheetTitle></SheetHeader>
        <p className="text-xs text-muted-foreground">
          Asked of every candidate for this role. Editing these does not change
          interviews already generated.
        </p>
        {rows.map((row, i) => (
          <div key={row.id} className="flex gap-2 items-end">
            <div className="flex-1 space-y-1">
              <Label htmlFor={`baseline-${row.id}`}>Baseline question {i + 1}</Label>
              <Input
                id={`baseline-${row.id}`}
                value={row.text}
                onChange={(e) =>
                  setRows((rs) => rs.map((r) =>
                    r.id === row.id ? { ...r, text: e.target.value } : r))}
              />
            </div>
            <Button
              variant="ghost"
              size="sm"
              aria-label={`Remove baseline question ${i + 1}`}
              onClick={() => setRows((rs) => rs.filter((r) => r.id !== row.id))}
            >
              Remove
            </Button>
          </div>
        ))}
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() =>
              setRows((rs) => [...rs, { id: `b-${Date.now()}-${rs.length}`, text: "" }])}
          >
            Add question
          </Button>
          {/* Blank rows are dropped rather than rejected: an empty row is an
              abandoned edit, not an error worth blocking a save for. */}
          <Button onClick={() => save.mutate(rows.filter((r) => r.text.trim()))}>
            Save
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
```

- [ ] **Step 4: Open it from the job page**

In `recruiter-frontend/src/routes/job-detail.tsx`, mirroring how the criteria
sheet is opened:

```tsx
const [baselineOpen, setBaselineOpen] = useState(false);

// inside the Manage job menu, beside the Edit criteria item:
<DropdownMenuItem onSelect={() => setBaselineOpen(true)}>
  Baseline questions
</DropdownMenuItem>

// beside <EditCriteriaSheet ... />:
<EditInterviewBaselineSheet
  jobId={jobId}
  open={baselineOpen}
  onOpenChange={setBaselineOpen}
/>
```

Import `EditInterviewBaselineSheet`, and match the menu component actually used
there — if the menu is not `DropdownMenu`, use whatever `Edit criteria` uses.

- [ ] **Step 5: Run test to verify it passes**

Run: `npx vitest --run src/components/jobs/edit-interview-baseline-sheet.test.tsx`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add recruiter-frontend/src/components/jobs/edit-interview-baseline-sheet.tsx \
        recruiter-frontend/src/components/jobs/edit-interview-baseline-sheet.test.tsx \
        recruiter-frontend/src/routes/job-detail.tsx
git commit -m "feat(interview): edit a job's baseline questions"
```

---

### Task 12: End-to-end

**Files:**
- Create: `recruiter-frontend/e2e/interview-kit.spec.ts`

**Interfaces:**
- Consumes: everything above, plus the shared session from `e2e/auth.setup.ts`.
- Produces: nothing other code depends on.

The suite authenticates once via the setup project, so this spec must **not** call `login()` — see `e2e/auth.setup.ts`. Follow the self-discovering pattern of `e2e/rescore-on-criteria-change.spec.ts`: find data through the API, skip if it is absent, restore what you mutate.

- [ ] **Step 1: Write the spec**

```ts
// recruiter-frontend/e2e/interview-kit.spec.ts
import { expect, test, type Page } from "@playwright/test";

interface JobSummary { id: number }
interface AppSummary { id: number; stage: string }

/** A candidate sitting at `scheduled` is what this flow needs; the kit is
 *  generated on entering that stage. */
async function findScheduledApplication(
  page: Page,
): Promise<{ jobId: number; appId: number } | null> {
  const jobs = (await (await page.request.get("/api/jobs")).json()) as JobSummary[];
  for (const job of jobs) {
    const apps = (await (await page.request.get(
      `/api/jobs/${job.id}/applications`)).json()) as AppSummary[];
    const scheduled = apps.find((a) => a.stage === "scheduled");
    if (scheduled) return { jobId: job.id, appId: scheduled.id };
  }
  return null;
}

test.describe("interview kit", () => {
  test("generate, answer, submit — candidate becomes interviewed", async ({ page }) => {
    const found = await findScheduledApplication(page);
    test.skip(found === null, "no scheduled application in local DB");
    await page.goto(`/applications/${found!.appId}`);

    // The kit may already be generating from the stage transition; if there is
    // nothing at all, ask for one.
    const generate = page.getByRole("button", { name: /generate interview kit/i });
    if (await generate.isVisible().catch(() => false)) await generate.click();

    const firstAnswer = page.getByPlaceholder(/what they said/i).first();
    await expect(firstAnswer).toBeVisible({ timeout: 60_000 });
    await firstAnswer.fill("Ran the platform for two years.");

    page.once("dialog", (d) => d.accept());
    await page.getByRole("button", { name: /submit interview/i }).click();

    await expect
      .poll(async () => {
        const app = await (await page.request.get(
          `/api/applications/${found!.appId}`)).json();
        return app.stage;
      }, { timeout: 30_000 })
      .toBe("interviewed");
  });
});
```

- [ ] **Step 2: Run it against the running stack**

Run: `docker compose up -d && npx playwright test e2e/interview-kit.spec.ts --reporter=list`
Expected: PASS, or SKIP if no scheduled candidate exists locally — in which case move one to Scheduled in the UI first and re-run, so the spec is actually exercised at least once.

- [ ] **Step 3: Run the whole e2e suite**

Run: `npx playwright test --reporter=list`
Expected: all pass. This confirms the new spec has not disturbed the shared-session arrangement.

- [ ] **Step 4: Commit**

```bash
git add recruiter-frontend/e2e/interview-kit.spec.ts
git commit -m "test(e2e): cover the interview kit flow end to end"
```

---

## Final verification

- [ ] `uv run pytest -q` — all pass
- [ ] `uv run ruff check src/` — no more than 233 errors
- [ ] `cd recruiter-frontend && npx vitest --run` — all pass
- [ ] `npm run lint` — silent
- [ ] `npx playwright test` — all pass
- [ ] `docker compose build backend frontend && docker compose up -d --force-recreate` — then generate a kit on a real candidate and **read the questions**. The spec names this explicitly as a risk tests cannot cover: if the probes are blander than what a recruiter would write unaided, the feature has failed its purpose even with every test green.
