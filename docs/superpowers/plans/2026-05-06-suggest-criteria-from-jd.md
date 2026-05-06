# Suggest Criteria From Job Description — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an LLM-backed "Suggest from JD" button to the New Job form that prefills the criteria field-array with 3–6 weighted criteria the user can keep or edit.

**Architecture:** New stateless endpoint `POST /api/jobs/criteria/suggest` calls a new `pipeline/criteria_suggester.py` module that uses the existing `LLMClient.chat_structured` with weight normalization and a count clamp. Frontend adds a single button + confirm-on-replace dialog; on success the field-array is replaced atomically.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy async, pytest (asyncio + httpx); React 18, react-hook-form, TanStack Query, vitest + msw, shadcn Dialog primitive, Sonner toasts.

**Spec:** `docs/superpowers/specs/2026-05-06-suggest-criteria-from-jd-design.md`

---

## File map

**Backend create:**
- `src/recruiter/schemas/job_suggest.py` — request/response models for the new endpoint
- `src/recruiter/pipeline/criteria_suggester.py` — LLM call + weight normalization + count clamp
- `tests/unit/test_criteria_suggester.py` — pipeline-level unit tests
- `tests/api/test_jobs_criteria_suggest_api.py` — endpoint-level tests

**Backend modify:**
- `src/recruiter/api/jobs.py` — add the `POST /criteria/suggest` route + LLM dep wiring

**Frontend create:**
- `recruiter-frontend/src/routes/jobs-new.test.tsx` — component-level test for the new button + confirm dialog

**Frontend modify:**
- `recruiter-frontend/src/routes/jobs-new.tsx` — add button, mutation, confirm dialog

**Optional E2E:**
- `scripts/e2e-suggest-criteria.mjs` — headed Playwright walkthrough (Task 6, optional)

---

## Task 1: Backend schemas

**Files:**
- Create: `src/recruiter/schemas/job_suggest.py`

- [ ] **Step 1: Write the schemas file**

```python
# src/recruiter/schemas/job_suggest.py
from pydantic import BaseModel, Field

from recruiter.schemas.job import CriteriaItem


class SuggestCriteriaRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str = Field(min_length=50)


class SuggestCriteriaResponse(BaseModel):
    criteria: list[CriteriaItem]


# Internal LLM-output schema. Lives next to its consumer; not re-exported.
class SuggestedCriterion(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    weight: float = Field(ge=0.0, le=1.0)
    description: str = Field(min_length=1)


class SuggestedCriteria(BaseModel):
    criteria: list[SuggestedCriterion]
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `uv run python -c "from recruiter.schemas.job_suggest import SuggestCriteriaRequest, SuggestCriteriaResponse, SuggestedCriteria; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/recruiter/schemas/job_suggest.py
git commit -m "feat(schemas): suggest-criteria request/response models"
```

---

## Task 2: Pipeline — write the failing tests

**Files:**
- Create: `tests/unit/test_criteria_suggester.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_criteria_suggester.py
import pytest

from recruiter.llm.client import FakeLLMClient
from recruiter.pipeline.criteria_suggester import suggest_criteria
from recruiter.schemas.job_suggest import SuggestedCriteria, SuggestedCriterion


def _resp(items: list[tuple[str, float, str]]) -> SuggestedCriteria:
    return SuggestedCriteria(
        criteria=[SuggestedCriterion(name=n, weight=w, description=d) for n, w, d in items],
    )


@pytest.mark.asyncio
async def test_passes_through_a_well_formed_response() -> None:
    fake = FakeLLMClient(structured_responses=[
        _resp([
            ("Java expertise", 0.40, "5+ years professional Java"),
            ("Spring framework", 0.30, "Production Spring Boot"),
            ("System design", 0.20, "Designed distributed services"),
            ("Communication", 0.10, "Clear written/verbal communication"),
        ]),
    ])
    out = await suggest_criteria(
        title="Senior Java Developer",
        description="We are looking for a Senior Java Developer with strong Spring experience...",
        llm=fake,
    )
    assert len(out) == 4
    assert out[0].name == "Java expertise"
    assert sum(c.weight for c in out) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_normalizes_weights_to_sum_one() -> None:
    fake = FakeLLMClient(structured_responses=[
        _resp([("A", 0.30, "x"), ("B", 0.30, "x"), ("C", 0.30, "x"), ("D", 0.30, "x")]),
    ])
    out = await suggest_criteria(
        title=None,
        description="x" * 60,
        llm=fake,
    )
    total = sum(c.weight for c in out)
    assert total == pytest.approx(1.0)
    # Residual must land on the largest weight after rounding.
    assert all(0.0 <= c.weight <= 1.0 for c in out)


@pytest.mark.asyncio
async def test_reprompts_once_when_count_below_three() -> None:
    fake = FakeLLMClient(structured_responses=[
        _resp([("A", 1.0, "x"), ("B", 0.0, "y")]),  # 2 — too few
        _resp([("A", 0.4, "x"), ("B", 0.3, "y"), ("C", 0.3, "z")]),  # valid
    ])
    out = await suggest_criteria(title="t", description="x" * 60, llm=fake)
    assert len(out) == 3


@pytest.mark.asyncio
async def test_raises_when_count_off_after_reprompt() -> None:
    fake = FakeLLMClient(structured_responses=[
        _resp([("A", 1.0, "x"), ("B", 0.0, "y")]),
        _resp([("A", 1.0, "x"), ("B", 0.0, "y")]),
    ])
    with pytest.raises(ValueError):
        await suggest_criteria(title="t", description="x" * 60, llm=fake)


@pytest.mark.asyncio
async def test_prompt_includes_title_and_description() -> None:
    fake = FakeLLMClient(structured_responses=[
        _resp([("A", 0.5, "x"), ("B", 0.3, "y"), ("C", 0.2, "z")]),
    ])
    await suggest_criteria(
        title="Backend Engineer",
        description="Build Rust APIs. " * 5,
        llm=fake,
    )
    sent = fake.calls[0]
    user_msg = next(m for m in sent["messages"] if m.role == "user")
    assert "Backend Engineer" in user_msg.content
    assert "Build Rust APIs" in user_msg.content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_criteria_suggester.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'recruiter.pipeline.criteria_suggester'`

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/unit/test_criteria_suggester.py
git commit -m "test(pipeline): failing tests for criteria_suggester"
```

---

## Task 3: Pipeline — implement to make tests pass

**Files:**
- Create: `src/recruiter/pipeline/criteria_suggester.py`

- [ ] **Step 1: Write the implementation**

```python
# src/recruiter/pipeline/criteria_suggester.py
from recruiter.llm.client import LLMClient, LLMMessage
from recruiter.schemas.job import CriteriaItem
from recruiter.schemas.job_suggest import SuggestedCriteria

_MIN_COUNT = 3
_MAX_COUNT = 6

_SYSTEM = """You are a recruiting expert. Given a job title and description, propose between 3 and 6 weighted scoring criteria a recruiter can use to evaluate candidates. Each criterion has:
- name: short, max 128 characters (e.g. "Java expertise")
- weight: float in [0, 1]; weights across all criteria must sum to 1.0
- description: one or two sentences explaining what evidence to look for

Avoid overlapping criteria. Avoid generic filler ("good communicator") unless the job description specifically emphasizes it. Output JSON only matching the requested schema."""


def _build_user_prompt(title: str | None, description: str, *, count_hint: str = "") -> str:
    head = f"Job title: {title}\n\n" if title else ""
    tail = f"\n\n{count_hint}" if count_hint else ""
    return (
        f"{head}Job description:\n{description}\n\n"
        f"Return between {_MIN_COUNT} and {_MAX_COUNT} criteria as the structured JSON.{tail}"
    )


def _normalize_weights(items: list[CriteriaItem]) -> list[CriteriaItem]:
    """Scale weights to sum to exactly 1.0 (within float epsilon)."""
    total = sum(c.weight for c in items)
    if total <= 0:
        # Degenerate — fall back to equal weights.
        equal = round(1.0 / len(items), 2)
        scaled = [c.model_copy(update={"weight": equal}) for c in items]
    else:
        scaled = [
            c.model_copy(update={"weight": round(c.weight / total, 2)}) for c in items
        ]
    # Push residual onto the largest weight so the final sum equals 1.0.
    residual = round(1.0 - sum(c.weight for c in scaled), 2)
    if residual != 0.0:
        idx = max(range(len(scaled)), key=lambda i: scaled[i].weight)
        bumped = scaled[idx].model_copy(update={"weight": round(scaled[idx].weight + residual, 2)})
        scaled[idx] = bumped
    return scaled


async def suggest_criteria(
    *,
    title: str | None,
    description: str,
    llm: LLMClient,
) -> list[CriteriaItem]:
    """Return 3-6 weighted criteria suggested by the LLM for this JD.

    Re-prompts once if the LLM returns the wrong number of criteria. Raises
    ValueError if still off after the retry.
    """
    user = _build_user_prompt(title, description)
    raw = await llm.chat_structured(
        messages=[LLMMessage(role="user", content=user)],
        schema=SuggestedCriteria,
        system=_SYSTEM,
        max_tokens=2048,
        temperature=0.2,
    )

    if not (_MIN_COUNT <= len(raw.criteria) <= _MAX_COUNT):
        # One retry with explicit count instruction.
        retry_user = _build_user_prompt(
            title, description,
            count_hint=f"You must return exactly between {_MIN_COUNT} and {_MAX_COUNT} criteria.",
        )
        raw = await llm.chat_structured(
            messages=[LLMMessage(role="user", content=retry_user)],
            schema=SuggestedCriteria,
            system=_SYSTEM,
            max_tokens=2048,
            temperature=0.2,
        )
        if not (_MIN_COUNT <= len(raw.criteria) <= _MAX_COUNT):
            raise ValueError(
                f"LLM returned {len(raw.criteria)} criteria after retry; "
                f"expected {_MIN_COUNT}-{_MAX_COUNT}"
            )

    items = [
        CriteriaItem(name=c.name, weight=c.weight, description=c.description)
        for c in raw.criteria
    ]
    return _normalize_weights(items)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_criteria_suggester.py -v`
Expected: 5 passed

- [ ] **Step 3: Commit**

```bash
git add src/recruiter/pipeline/criteria_suggester.py
git commit -m "feat(pipeline): criteria_suggester with weight normalization and count clamp"
```

---

## Task 4: API endpoint — write the failing tests

**Files:**
- Create: `tests/api/test_jobs_criteria_suggest_api.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_jobs_criteria_suggest_api.py
import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.schemas.job_suggest import SuggestedCriteria, SuggestedCriterion


def _fake_with(items: list[tuple[str, float, str]]) -> FakeLLMClient:
    return FakeLLMClient(structured_responses=[
        SuggestedCriteria(criteria=[
            SuggestedCriterion(name=n, weight=w, description=d) for n, w, d in items
        ]),
    ])


@pytest.mark.asyncio
async def test_suggest_criteria_happy_path(api_client: AsyncClient) -> None:
    fake = _fake_with([
        ("A", 0.40, "x"), ("B", 0.30, "y"), ("C", 0.20, "z"), ("D", 0.10, "w"),
    ])
    app.dependency_overrides[get_llm] = lambda: fake
    try:
        resp = await api_client.post(
            "/api/jobs/criteria/suggest",
            json={"title": "Backend", "description": "Build Rust APIs. " * 5},
        )
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["criteria"]) == 4
    weights = [c["weight"] for c in body["criteria"]]
    assert sum(weights) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_suggest_criteria_rejects_short_description(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/jobs/criteria/suggest",
        json={"title": "x", "description": "too short"},
    )
    assert resp.status_code == 422  # Pydantic min_length=50


@pytest.mark.asyncio
async def test_suggest_criteria_returns_502_on_llm_failure(api_client: AsyncClient) -> None:
    # Empty FakeLLMClient → raises RuntimeError on first call.
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()
    try:
        resp = await api_client.post(
            "/api/jobs/criteria/suggest",
            json={"description": "x" * 80},
        )
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_suggest_criteria_requires_auth(api_client_unauth: AsyncClient) -> None:
    resp = await api_client_unauth.post(
        "/api/jobs/criteria/suggest",
        json={"description": "x" * 80},
    )
    assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_jobs_criteria_suggest_api.py -v`
Expected: FAIL — endpoint returns 404 (not yet defined). The auth test should pass already if the route is missing — that's fine; we'll re-run after Task 5.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/api/test_jobs_criteria_suggest_api.py
git commit -m "test(api): failing tests for POST /api/jobs/criteria/suggest"
```

---

## Task 5: API endpoint — implement to make tests pass

**Files:**
- Modify: `src/recruiter/api/jobs.py`

- [ ] **Step 1: Wire the new route into `jobs.py`**

Open `src/recruiter/api/jobs.py` and replace its full contents with:

```python
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.candidates import get_llm
from recruiter.api.deps import get_session, require_user
from recruiter.llm.client import LLMClient
from recruiter.models import Job, JobStatus
from recruiter.pipeline.criteria_suggester import suggest_criteria
from recruiter.schemas.job import CriteriaItem, JobCreate, JobRead, JobUpdate
from recruiter.schemas.job_suggest import SuggestCriteriaRequest, SuggestCriteriaResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"], dependencies=[Depends(require_user)])


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_job(payload: JobCreate, session: AsyncSession = Depends(get_session)) -> JobRead:
    job = Job(
        title=payload.title,
        description=payload.description,
        criteria=[c.model_dump() for c in payload.criteria],
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return _to_read(job)


@router.get("", response_model=list[JobRead])
async def list_jobs(session: AsyncSession = Depends(get_session)) -> list[JobRead]:
    rows = (await session.execute(select(Job).order_by(Job.created_at.desc()))).scalars().all()
    return [_to_read(j) for j in rows]


@router.post("/criteria/suggest", response_model=SuggestCriteriaResponse)
async def suggest_criteria_endpoint(
    payload: SuggestCriteriaRequest,
    llm: LLMClient = Depends(get_llm),
) -> SuggestCriteriaResponse:
    """Suggest 3-6 weighted criteria from a job description.

    Stateless — no DB writes. Returns 502 on any LLM-side failure to match
    the upstream-error convention used elsewhere in the API.
    """
    try:
        items = await suggest_criteria(
            title=payload.title,
            description=payload.description,
            llm=llm,
        )
    except Exception as exc:
        logger.warning("criteria suggestion failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="Criteria suggestion failed") from exc
    return SuggestCriteriaResponse(criteria=items)


@router.get("/{job_id}", response_model=JobRead)
async def get_job(job_id: int, session: AsyncSession = Depends(get_session)) -> JobRead:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _to_read(job)


@router.patch("/{job_id}", response_model=JobRead)
async def update_job(
    job_id: int, payload: JobUpdate, session: AsyncSession = Depends(get_session)
) -> JobRead:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if payload.title is not None:
        job.title = payload.title
    if payload.description is not None:
        job.description = payload.description
    if payload.criteria is not None:
        job.criteria = [c.model_dump() for c in payload.criteria]
    if payload.status is not None:
        job.status = JobStatus(payload.status)
    await session.commit()
    await session.refresh(job)
    return _to_read(job)


def _to_read(job: Job) -> JobRead:
    return JobRead(
        id=job.id,
        title=job.title,
        description=job.description,
        criteria=[CriteriaItem.model_validate(c) for c in (job.criteria or [])],
        status=job.status.value,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
```

> **Note on route ordering:** `POST /criteria/suggest` is declared **before** `GET /{job_id}` so FastAPI does not interpret `criteria` as a path-parameter value. If you reorder later, you'll get a 422 trying to coerce `"criteria"` to int.

- [ ] **Step 2: Run the API tests to verify they pass**

Run: `uv run pytest tests/api/test_jobs_criteria_suggest_api.py tests/api/test_jobs_api.py -v`
Expected: all tests pass (existing `test_jobs_api.py` is a regression check on the route ordering).

- [ ] **Step 3: Commit**

```bash
git add src/recruiter/api/jobs.py
git commit -m "feat(api): POST /api/jobs/criteria/suggest endpoint"
```

---

## Task 6: Frontend — write the failing test

**Files:**
- Create: `recruiter-frontend/src/routes/jobs-new.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// recruiter-frontend/src/routes/jobs-new.test.tsx
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { Toaster } from "sonner";
import JobsNew from "./jobs-new";

const server = setupServer();

function renderJobsNew() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <JobsNew />
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("JobsNew — Suggest from JD", () => {
  beforeEach(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => {
    server.resetHandlers();
    server.close();
  });

  it("disables the button while the description is short", async () => {
    renderJobsNew();
    const btn = screen.getByRole("button", { name: /suggest from jd/i });
    expect(btn).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/description/i), "short text");
    expect(btn).toBeDisabled();
  });

  it("enables the button when description reaches 50 chars", async () => {
    renderJobsNew();
    await userEvent.type(
      screen.getByLabelText(/description/i),
      "a".repeat(60),
    );
    expect(screen.getByRole("button", { name: /suggest from jd/i })).toBeEnabled();
  });

  it("populates criteria when clicked on an empty list", async () => {
    server.use(
      http.post("http://localhost:8000/api/jobs/criteria/suggest", async () =>
        HttpResponse.json({
          criteria: [
            { name: "Java", weight: 0.5, description: "Java expertise" },
            { name: "Spring", weight: 0.3, description: "Spring framework" },
            { name: "SQL", weight: 0.2, description: "Database skills" },
          ],
        }),
      ),
    );
    renderJobsNew();
    await userEvent.type(screen.getByLabelText(/description/i), "a".repeat(60));
    await userEvent.click(screen.getByRole("button", { name: /suggest from jd/i }));

    await waitFor(() => {
      expect(screen.getByDisplayValue("Java")).toBeInTheDocument();
      expect(screen.getByDisplayValue("Spring")).toBeInTheDocument();
      expect(screen.getByDisplayValue("SQL")).toBeInTheDocument();
    });
  });

  it("shows confirm dialog when criteria already exist; cancel preserves rows", async () => {
    renderJobsNew();
    await userEvent.type(screen.getByLabelText(/description/i), "a".repeat(60));

    // Add a manual criterion first.
    await userEvent.click(screen.getByRole("button", { name: /add criterion/i }));
    const nameInput = await screen.findByPlaceholderText("Name");
    await userEvent.type(nameInput, "MyCustom");

    await userEvent.click(screen.getByRole("button", { name: /suggest from jd/i }));

    // Confirm dialog appears.
    expect(await screen.findByText(/replace 1 existing/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^cancel$/i }));

    // Manual row preserved.
    expect(screen.getByDisplayValue("MyCustom")).toBeInTheDocument();
  });

  it("replaces criteria when confirm dialog is accepted", async () => {
    server.use(
      http.post("http://localhost:8000/api/jobs/criteria/suggest", async () =>
        HttpResponse.json({
          criteria: [
            { name: "Java", weight: 0.5, description: "x" },
            { name: "Spring", weight: 0.3, description: "y" },
            { name: "SQL", weight: 0.2, description: "z" },
          ],
        }),
      ),
    );
    renderJobsNew();
    await userEvent.type(screen.getByLabelText(/description/i), "a".repeat(60));
    await userEvent.click(screen.getByRole("button", { name: /add criterion/i }));
    await userEvent.type(await screen.findByPlaceholderText("Name"), "MyCustom");

    await userEvent.click(screen.getByRole("button", { name: /suggest from jd/i }));
    await userEvent.click(await screen.findByRole("button", { name: /replace/i }));

    await waitFor(() => {
      expect(screen.queryByDisplayValue("MyCustom")).not.toBeInTheDocument();
      expect(screen.getByDisplayValue("Java")).toBeInTheDocument();
    });
  });

  it("shows error toast on 500 and leaves criteria untouched", async () => {
    server.use(
      http.post("http://localhost:8000/api/jobs/criteria/suggest", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    renderJobsNew();
    await userEvent.type(screen.getByLabelText(/description/i), "a".repeat(60));
    await userEvent.click(screen.getByRole("button", { name: /suggest from jd/i }));

    expect(await screen.findByText(/couldn't suggest criteria/i)).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Name")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd recruiter-frontend && npx vitest run src/routes/jobs-new.test.tsx`
Expected: FAIL — there's no "Suggest from JD" button on `JobsNew` yet.

- [ ] **Step 3: Commit failing tests**

```bash
git add recruiter-frontend/src/routes/jobs-new.test.tsx
git commit -m "test(jobs-new): failing tests for Suggest-from-JD button + confirm dialog"
```

---

## Task 7: Frontend — implement the button + mutation + confirm dialog

**Files:**
- Modify: `recruiter-frontend/src/routes/jobs-new.tsx`

- [ ] **Step 1: Replace `jobs-new.tsx` with the new implementation**

```tsx
// recruiter-frontend/src/routes/jobs-new.tsx
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { zodResolver } from "@hookform/resolvers/zod";
import { useFieldArray, useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { z } from "zod";
import { Plus, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

const Criterion = z.object({
  name: z.string().min(1, "Required"),
  weight: z.coerce.number().min(0).max(1),
  description: z.string().min(1, "Required"),
});

const Schema = z.object({
  title: z.string().min(1, "Title is required").max(255),
  description: z.string().min(1, "Description is required"),
  criteria: z.array(Criterion),
});

type FormValues = z.infer<typeof Schema>;

interface JobReadResp {
  id: number;
}

interface SuggestResponse {
  criteria: Array<{ name: string; weight: number; description: string }>;
}

const DESCRIPTION_MIN_FOR_SUGGEST = 50;

export default function JobsNew() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const form = useForm<FormValues>({
    resolver: zodResolver(Schema),
    defaultValues: { title: "", description: "", criteria: [] },
  });
  const criteria = useFieldArray({ control: form.control, name: "criteria" });
  const description = form.watch("description") ?? "";
  const [confirmOpen, setConfirmOpen] = useState(false);

  const createJob = useMutation({
    mutationFn: (values: FormValues) =>
      api<JobReadResp>("/api/jobs", { method: "POST", json: values }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs() });
      navigate(`/jobs/${data.id}`);
    },
  });

  const suggestCriteria = useMutation({
    mutationFn: (payload: { title: string; description: string }) =>
      api<SuggestResponse>("/api/jobs/criteria/suggest", {
        method: "POST",
        json: payload,
      }),
    onSuccess: (resp) => {
      criteria.replace(resp.criteria);
    },
    onError: () => {
      toast.error("Couldn't suggest criteria — try again.");
    },
  });

  const onSuggestClick = () => {
    if (criteria.fields.length > 0) {
      setConfirmOpen(true);
      return;
    }
    suggestCriteria.mutate({
      title: form.getValues("title"),
      description,
    });
  };

  const onConfirmReplace = () => {
    setConfirmOpen(false);
    suggestCriteria.mutate({
      title: form.getValues("title"),
      description,
    });
  };

  const suggestDisabled =
    description.length < DESCRIPTION_MIN_FOR_SUGGEST || suggestCriteria.isPending;

  return (
    <form
      onSubmit={form.handleSubmit((v) => createJob.mutate(v))}
      className="space-y-6 max-w-3xl"
    >
      <h2 className="text-xl font-semibold">New job</h2>

      <div className="space-y-2">
        <Label htmlFor="title">Title</Label>
        <Input id="title" {...form.register("title")} />
        {form.formState.errors.title && (
          <p className="text-sm text-destructive">{form.formState.errors.title.message}</p>
        )}
      </div>

      <div className="space-y-2">
        <Label htmlFor="description">Description (job description / JD)</Label>
        <Textarea id="description" rows={10} {...form.register("description")} />
        {form.formState.errors.description && (
          <p className="text-sm text-destructive">{form.formState.errors.description.message}</p>
        )}
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label>Custom criteria (optional)</Label>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={suggestDisabled}
              onClick={onSuggestClick}
            >
              <Sparkles className="h-4 w-4 mr-1" />
              {suggestCriteria.isPending ? "Suggesting…" : "Suggest from JD"}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => criteria.append({ name: "", weight: 0.5, description: "" })}
            >
              <Plus className="h-4 w-4 mr-1" />
              Add criterion
            </Button>
          </div>
        </div>
        {criteria.fields.map((field, index) => (
          <div key={field.id} className="grid grid-cols-[1fr_100px_2fr_auto] gap-2 items-start">
            <Input placeholder="Name" {...form.register(`criteria.${index}.name`)} />
            <Input
              placeholder="0.5"
              type="number"
              step="0.1"
              {...form.register(`criteria.${index}.weight`)}
            />
            <Input placeholder="Description" {...form.register(`criteria.${index}.description`)} />
            <Button type="button" variant="ghost" size="icon" onClick={() => criteria.remove(index)}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ))}
      </div>

      <div className="flex gap-2">
        <Button type="submit" disabled={createJob.isPending}>
          {createJob.isPending ? "Creating…" : "Create job"}
        </Button>
        <Button type="button" variant="outline" onClick={() => navigate(-1)}>
          Cancel
        </Button>
      </div>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Replace existing criteria?</DialogTitle>
            <DialogDescription>
              Replace {criteria.fields.length} existing{" "}
              {criteria.fields.length === 1 ? "criterion" : "criteria"} with suggestions from
              the job description? This can't be undone — but you can edit the suggestions
              after.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button type="button" onClick={onConfirmReplace}>
              Replace
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </form>
  );
}
```

- [ ] **Step 2: Run the tests to verify they pass**

Run: `cd recruiter-frontend && npx vitest run src/routes/jobs-new.test.tsx`
Expected: 6 passed.

- [ ] **Step 3: Run a typecheck pass to confirm no regressions**

Run: `cd recruiter-frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add recruiter-frontend/src/routes/jobs-new.tsx
git commit -m "feat(jobs-new): Suggest from JD button with confirm-on-replace dialog"
```

---

## Task 8: Optional — headed Playwright smoke

**Files:**
- Create: `scripts/e2e-suggest-criteria.mjs`

> Skip this task if you don't have a real LLM key configured locally — the endpoint will return 502 in dev unless `RECRUITER_DEV_AUTH_BYPASS` is set AND the Settings row has a working `default_llm_provider`. In that case, gate the script on a local check.

- [ ] **Step 1: Write the script**

```javascript
#!/usr/bin/env node
// Headed Playwright smoke for Suggest-from-JD.
//
// Prereqs:
//   - Backend on http://localhost:8765 with dev-bypass auth
//   - Frontend on http://localhost:5173
//   - Settings row has a working LLM provider configured
//
// Run: node scripts/e2e-suggest-criteria.mjs

import { chromium } from "playwright";

const FRONTEND = "http://localhost:5173";

function log(m) { console.log(`[e2e] ${m}`); }

async function main() {
  const browser = await chromium.launch({ headless: false, slowMo: 250 });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error") console.log(`[browser:error] ${m.text()}`); });

  try {
    log("Opening /jobs/new");
    await page.goto(`${FRONTEND}/jobs/new`);

    log("Filling title and description");
    await page.getByLabel(/title/i).fill("Senior Java Developer");
    await page.getByLabel(/description/i).fill(
      "We are looking for a Senior Java Developer with 5+ years of professional Java, " +
      "production Spring Boot experience, distributed systems design, and clear written communication. " +
      "Experience with PostgreSQL and Kafka is a plus."
    );

    log("Clicking Suggest from JD");
    await page.getByRole("button", { name: /suggest from jd/i }).click();

    log("Waiting for suggested rows to appear");
    await page.locator('input[placeholder="Name"]').first().waitFor({ timeout: 30000 });
    const rows = await page.locator('input[placeholder="Name"]').count();
    log(`✓ ${rows} criteria suggested`);
    if (rows < 3 || rows > 6) {
      throw new Error(`expected 3-6 criteria, got ${rows}`);
    }

    log("Adding a manual row, then clicking Suggest again to test confirm dialog");
    await page.getByRole("button", { name: /add criterion/i }).click();
    await page.getByRole("button", { name: /suggest from jd/i }).click();
    await page.getByRole("heading", { name: /replace existing criteria/i }).waitFor();
    log("✓ confirm dialog visible");

    await page.getByRole("button", { name: /^cancel$/i }).click();
    log("✓ cancel preserves rows");

    log("ALL CHECKS PASSED");
    await page.waitForTimeout(2000);
  } catch (err) {
    console.error(`[e2e] FAIL: ${err.message}`);
    await page.screenshot({ path: "/tmp/e2e-suggest-criteria-fail.png", fullPage: true });
    process.exit(1);
  } finally {
    await browser.close();
  }
}

main();
```

- [ ] **Step 2: Manual run (optional)**

Run: `node scripts/e2e-suggest-criteria.mjs`
Expected: Browser opens, fills the form, suggested criteria appear, confirm dialog visible, "ALL CHECKS PASSED".

- [ ] **Step 3: Commit**

```bash
git add scripts/e2e-suggest-criteria.mjs
git commit -m "test(e2e): headed Playwright smoke for Suggest-from-JD"
```

---

## Final verification

- [ ] **Run the full backend test suite to confirm no regressions**

Run: `uv run pytest tests/unit/test_criteria_suggester.py tests/api/test_jobs_criteria_suggest_api.py tests/api/test_jobs_api.py -v`
Expected: all green.

- [ ] **Run the full frontend test suite**

Run: `cd recruiter-frontend && npx vitest run`
Expected: all green.

- [ ] **Confirm the suggest button is functional end-to-end**

Manually: with backend on `:8765` and frontend on `:5173`, go to `/jobs/new`, paste a real JD, click "Suggest from JD", verify rows populate. (Requires a valid LLM provider in Settings.)

---

## Self-review checklist

- [x] **Spec coverage:** every section of the spec maps to a task. Backend endpoint = Tasks 4–5. Pipeline = Tasks 2–3. Schemas = Task 1. Frontend = Tasks 6–7. Tests covered in each TDD pair. E2E = Task 8 (optional).
- [x] **Placeholders:** none — every code block is complete.
- [x] **Type consistency:** `CriteriaItem`, `SuggestedCriteria`, `SuggestCriteriaRequest`, `SuggestCriteriaResponse` are used consistently across schemas, pipeline, API, and frontend.
- [x] **Status code convention:** `502` is the project's existing pattern for upstream LLM failures (no other endpoint disagrees). Pydantic `min_length=50` returns `422` (FastAPI default), tests assert on that.
- [x] **Route ordering:** `/criteria/suggest` declared before `/{job_id}` to avoid the int-coercion 422 trap. Called out inline.
- [x] **Frontend dialog primitive:** confirmed only `Dialog` exists (no `AlertDialog`); plan uses `Dialog` with `DialogHeader`/`Title`/`Description`/`Footer`.
