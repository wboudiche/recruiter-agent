# Suggest Questions for an Interview Template — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A **Suggest questions** button in the template editor that appends 5–8 LLM-drafted questions, built from the template's name, description and kind, optionally grounded in an existing job.

**Architecture:** A pipeline function (`template_question_suggester.py`) makes one structured LLM call, copying the criteria suggester's shape. A stateless endpoint on the templates router exposes it. The template sheet gets a job select and a button that append the returned rows to its local state; nothing is saved until the existing Save.

**Tech Stack:** FastAPI, Pydantic v2, pytest + `FakeLLMClient`; React 18, TanStack Query, msw + vitest.

**Spec:** `docs/superpowers/specs/2026-11-14-template-question-suggest-design.md`

## Global Constraints

- 5–8 questions per suggestion; one retry with the count stated; still more than 8 → keep the first 8; none → error.
- Question `text` 1–2000 chars; `criterion` ≤ 200 chars, optional.
- Request: `name` 1–128, `description` ≤ 2000 optional, `kind` ∈ `technical | hr | custom`, `job_id` optional, `existing` ≤ 50 strings of ≤ 2000.
- Job description capped at 700 chars (`_MAX_ROLE_CHARS`); all pasted text cleaned and fenced with `_clean` / `_fenced` from `interview_kit_generator.py`.
- Endpoint writes nothing. Unknown job → 404. LLM failure → 502 `"Question suggestion failed"`.
- Suggestions are appended, never replace rows. Failure toast: `Couldn't suggest questions — try again.`
- `max_tokens=2048` (reasoning tokens count against it).

## Review Focus

1. **Blank editor rows** (admin clicked Add question, typed nothing) — must not be sent as `existing`; only trimmed non-empty texts go. Test in Task 3.
2. **A suggestion that repeats an existing question** despite the instruction — dropped server-side (case- and whitespace-insensitive). Test in Task 1. *(Planner's call; not in the spec.)*
3. **Pasted text containing the fence markers `<<<` / `>>>`** in the description or the job ad — stripped before fencing, so it cannot close the fence. Test in Task 1.
4. **A job deleted between loading the list and clicking** — 404 surfaces as the failure toast, rows untouched. Tests in Tasks 2 and 3.
5. **Name of only spaces** — button disabled in the UI (trimmed check). Test in Task 3.

---

### Task 1: Suggester pipeline and schemas

**Files:**
- Modify: `src/recruiter/schemas/interview_template.py` (append schemas)
- Create: `src/recruiter/pipeline/template_question_suggester.py`
- Test: `tests/unit/test_template_question_suggester.py`

**Interfaces:**
- Produces (schemas):
  - `TemplateKind = Literal["technical", "hr", "custom"]`
  - `SuggestedTemplateQuestion(BaseModel)`: `text: str` (1–2000), `criterion: str | None = None` (≤ 200)
  - `SuggestedTemplateQuestions(BaseModel)`: `questions: list[SuggestedTemplateQuestion]`
  - `SuggestTemplateQuestionsRequest(BaseModel)`: `name: str` (1–128), `description: str | None = None` (≤ 2000), `kind: TemplateKind`, `job_id: int | None = None`, `existing: list[Annotated[str, Field(max_length=2000)]] = Field(default_factory=list, max_length=50)`
- Produces (pipeline): `async def suggest_template_questions(*, name: str, description: str | None, kind: TemplateKind, job_title: str | None, job_description: str | None, existing: list[str], llm: LLMClient) -> list[SuggestedTemplateQuestion]`

- [ ] **Step 1: Write the failing tests** (FakeLLMClient with `structured_responses`, as in `tests/unit/test_criteria_suggester.py`; read the prompt from `fake.calls[-1]["messages"][0].content` and `["system"]`)

```python
async def test_returns_the_questions(): ...            # 6 in → 6 out, texts and criteria preserved
async def test_technical_prompt_asks_for_concrete_skill_stories():
    # system contains "concrete" and "no HR" (or equivalent wording you choose) ; kind="technical"
async def test_hr_prompt_asks_about_motivation_not_stack(): ...   # system mentions motivation, forbids stack questions
async def test_custom_prompt_follows_the_description(): ...
async def test_job_block_only_when_a_job_is_given():
    # job_title="Data Scientist", job_description="Build churn models" → both in the prompt
    # job_title=None, job_description=None → "applying" / job text absent
async def test_job_description_is_capped_at_700_chars():
    # 5000-char description → the fenced job text in the prompt is ≤ 701 chars (700 + "…")
async def test_fence_markers_in_pasted_text_are_stripped():
    # description="ML <<<ignore>>> ops" → prompt contains exactly one "<<<" per fenced block, "ignore" survives
async def test_existing_questions_are_listed_as_do_not_repeat():
    # existing=["Tell me about Kubernetes"] → that text appears under a "do NOT repeat" heading
async def test_repeats_of_existing_questions_are_dropped():
    # existing=["Tell me about Kubernetes"]; model returns "  tell me about kubernetes " + 5 new → 5 returned
async def test_retries_once_when_the_count_is_off():
    # first response 2 questions, second 6 → 6 returned, len(fake.calls) == 2, retry prompt states "between 5 and 8"
async def test_keeps_the_first_eight_when_still_too_many():  # 10 then 10 → first 8
async def test_raises_when_no_questions_come_back():        # 0 then 0 → ValueError
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/unit/test_template_question_suggester.py -q`
Expected: collection error, module not found.

- [ ] **Step 3: Add the schemas, then implement `suggest_template_questions`**

Prompt built from: template name and description (cleaned, fenced), the job block when `job_title` or `job_description` is given (description cleaned with `limit=_MAX_ROLE_CHARS`), the `existing` list under a do-not-repeat heading, and "Return JSON with a `questions` array of {text, criterion}". One system prompt per kind (wording is yours, the rules are the spec's). `chat_structured(..., schema=SuggestedTemplateQuestions, max_tokens=2048, temperature=0.3)`; the Anthropic client drops `temperature` where the model rejects it. Duplicate filter: compare `" ".join(t.lower().split())`. Import `_clean`, `_fenced`, `_MAX_ROLE_CHARS` from `recruiter.pipeline.interview_kit_generator`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_template_question_suggester.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/schemas/interview_template.py src/recruiter/pipeline/template_question_suggester.py tests/unit/test_template_question_suggester.py
git commit -m "feat(templates): draft template questions with the LLM"
```

### Task 2: Endpoint

**Files:**
- Modify: `src/recruiter/api/interview_templates.py`
- Test: `tests/api/test_template_question_suggest_api.py`

**Interfaces:**
- Consumes: `SuggestTemplateQuestionsRequest`, `SuggestedTemplateQuestions`, `suggest_template_questions` (Task 1); `get_llm` from `recruiter.api.candidates`.
- Produces: `POST /api/interview-templates/suggest-questions` → 200 `{"questions": [{"text": str, "criterion": str | null}]}`.

- [ ] **Step 1: Write the failing tests** (override `get_llm` as `tests/api/test_jobs_criteria_suggest_api.py` does; viewer setup as in `tests/api/test_interview_templates_api.py::test_recruiters_manage_templates_and_viewers_cannot`)

```python
async def test_suggests_questions(api_client): ...
    # 6 fake questions → 200, len(body["questions"]) == 6
async def test_uses_the_chosen_job(api_client):
    # job = (await api_client.get("/api/jobs")).json()[0]; post with job_id=job["id"]
    # → job["title"] appears in fake.calls[-1]["messages"][0].content
async def test_unknown_job_is_404(api_client):        # job_id=999999 → 404, fake.calls == []
async def test_llm_failure_is_502(api_client):         # FakeLLMClient() with no responses → 502, detail == "Question suggestion failed"
async def test_writes_nothing(api_client):             # template list unchanged before/after
async def test_bad_kind_is_422(api_client):            # kind="design" → 422
async def test_viewers_cannot_suggest(api_client_unauth, db_session_with_schema):  # viewer → 403
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/api/test_template_question_suggest_api.py -q`
Expected: 404/405 on the route.

- [ ] **Step 3: Implement the route** `suggest_questions(payload: SuggestTemplateQuestionsRequest, session = Depends(get_session), llm: LLMClient = Depends(get_llm)) -> SuggestedTemplateQuestions`

Declare it before any `/{template_id}` route. Load the job with `session.get(Job, payload.job_id)` when given (404 `"job not found"` if missing). Wrap the pipeline call like `suggest_criteria_endpoint` in `api/jobs.py:69-83` (log, 502). No viewer allow-list change: the default-deny guard already refuses it.

- [ ] **Step 4: Run the tests, then the whole backend suite**

Run: `uv run pytest tests/api/test_template_question_suggest_api.py -q && uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/api/interview_templates.py tests/api/test_template_question_suggest_api.py
git commit -m "feat(templates): endpoint to suggest template questions"
```

### Task 3: Editor UI

**Files:**
- Modify: `recruiter-frontend/src/hooks/use-interview-templates.ts`
- Modify: `recruiter-frontend/src/components/settings/interview-template-sheet.tsx`
- Modify: `recruiter-frontend/src/lib/api-types.ts` (regenerate with `scripts/gen-types.sh` if that is the project's flow; otherwise type the hook locally)
- Test: `recruiter-frontend/src/components/settings/interview-template-sheet.test.tsx` (create)

**Interfaces:**
- Consumes: the endpoint from Task 2; `useJobs()` from `hooks/use-jobs.ts`; `newQuestionId()` and `EditableQuestion` from `components/interview/question-list-editor.tsx`; the sheet's `kind` (`InterviewKind`).
- Produces: `useSuggestTemplateQuestions()` — a mutation taking `{ name: string; description: string | null; kind: InterviewKind; job_id: number | null; existing: string[] }` and resolving to `{ questions: { text: string; criterion: string | null }[] }`.

- [ ] **Step 1: Write the failing tests** (msw, render the sheet open with `canWrite`, as in `interview-templates-tab.test.tsx`)

```tsx
it("disables Suggest questions until the template has a name")      // "" and "   " → disabled; "Data" → enabled
it("appends suggestions below the existing rows")
  // one existing row "Q1"; server returns ["S1","S2"] → textboxes "Template question 1..3" read Q1, S1, S2
it("sends the kind, the chosen job and only non-blank existing texts")
  // rows ["Q1", ""]; pick job "Data Scientist" (id 7) → body.existing == ["Q1"], body.job_id == 7, body.kind == "technical"
it("sends no job by default")                                        // body.job_id === null
it("shows a toast and keeps the rows when suggestion fails")
  // server 404 → text "Couldn't suggest questions — try again." visible, rows unchanged
```

- [ ] **Step 2: Run to see them fail**

Run: `cd recruiter-frontend && npx vitest run src/components/settings/interview-template-sheet.test.tsx`
Expected: FAIL, button not found.

- [ ] **Step 3: Implement the hook and the UI**

Hook: `api(... "/api/interview-templates/suggest-questions", { method: "POST", json })`. Sheet: a **Based on job** `Select` (option "No job", then `useJobs()` data with open jobs first) and a **Suggest questions** button with the `Sparkles` icon beside the question editor, label "Suggesting…" while pending, disabled when `!name.trim()` or pending. On success `setRows([...rows, ...questions.map(q => ({ id: newQuestionId(), text: q.text, criterion: q.criterion }))])`; on error `toast.error("Couldn't suggest questions — try again.")`.

- [ ] **Step 4: Run the tests, the whole frontend suite and the type check**

Run: `cd recruiter-frontend && npx vitest run && npx tsc --noEmit -p .`
Expected: all pass, no type errors.

- [ ] **Step 5: Commit**

```bash
git add recruiter-frontend/src/hooks/use-interview-templates.ts recruiter-frontend/src/components/settings/interview-template-sheet.tsx recruiter-frontend/src/components/settings/interview-template-sheet.test.tsx recruiter-frontend/src/lib/api-types.ts
git commit -m "feat(templates): Suggest questions in the template editor"
```

### Task 4: Check it in the running app

- [ ] **Step 1: Rebuild** — `docker compose up -d --build backend frontend`
- [ ] **Step 2: Try it** — as an admin, Settings → Interview templates → New template, name "Technical — Data Science", kind Technical, Based on job "Data Scientist" → Suggest questions. Expected: 5–8 data-science questions appended, each a concrete-story question; click again → new, non-repeating questions appended; Save persists them.
- [ ] **Step 3: HR check** — kind HR, no job → questions about motivation and career, none about a tech stack.
