# Suggest Criteria From Job Description — Design

**Author:** walid + claude
**Date:** 2026-05-06
**Status:** approved, ready for implementation plan

## Goal

Let the recruiter seed a job's scoring criteria from its job description with one click. On the **New Job** form, after pasting a JD, clicking **"Suggest from JD"** calls an LLM-backed endpoint and prefills the criteria field-array with 3–6 weighted criteria. The user keeps, edits, removes, or replaces them before submitting the job.

Today the form ships with `criteria: []` and forces the user to hand-craft each `{name, weight, description}` row. That's friction at the moment of highest value — most jobs never get good criteria entered, which degrades downstream scoring.

## Scope

### In scope (v1)

- New backend endpoint `POST /api/jobs/criteria/suggest` — stateless, no DB writes
- New module `src/recruiter/pipeline/criteria_suggester.py` mirroring `pipeline/scorer.py`
- `SuggestedCriteria` Pydantic schema for `LLMClient.chat_structured`
- Server-side weight normalization (sum to exactly 1.0)
- Server-side count clamp (3 ≤ count ≤ 6) — re-prompt if LLM drifts
- "Suggest from JD" button on `/jobs/new` next to "Add criterion"
- Description-length gate (≥ 50 chars) disables the button
- Confirm dialog when overwriting non-empty criteria
- Loading state, error toast, no partial fill on failure

### Out of scope (deferred)

- Edit Job form (`/jobs/:id/edit`) — same backend works there, UI to come later
- "Re-suggest from JD" action on the Job page itself
- Saving suggestion history / undo
- Per-row accept-or-reject preview dialog (Plan H-style multi-select UX)
- Streaming / progressive disclosure of criteria as the LLM emits them
- Localization of the LLM prompt (English-only v1)

## Architecture

```
┌────────────────┐   POST /api/jobs/criteria/suggest    ┌─────────────────────┐
│ /jobs/new      │ ────────────────────────────────────►│ api/jobs.py         │
│ "Suggest" btn  │   {title?, description}              │  → suggest_criteria()│
│                │ ◄────────────────────────────────────└──────────┬──────────┘
│ field-array    │   {criteria: [{name, weight, desc}]}            │
│ replace        │                                                 ▼
└────────────────┘                                  ┌─────────────────────────┐
                                                    │ pipeline/                │
                                                    │  criteria_suggester.py   │
                                                    │   chat_structured        │
                                                    │   weight normalization   │
                                                    │   count clamp / re-prompt│
                                                    └────────────┬─────────────┘
                                                                 ▼
                                                          LLMClient (Anthropic)
```

Auth: existing session middleware. `RECRUITER_DEV_AUTH_BYPASS` works locally; OIDC enforced in prod (same posture as `POST /api/jobs`).

## Data contracts

### Request

```python
class SuggestCriteriaRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str = Field(min_length=50)
```

### Response

```python
class SuggestCriteriaResponse(BaseModel):
    criteria: list[CriteriaItem]  # reuses existing schema in schemas/job.py
```

### Internal LLM-output schema

```python
class _SuggestedCriterion(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    weight: float = Field(ge=0.0, le=1.0)
    description: str = Field(min_length=1)

class _SuggestedCriteria(BaseModel):
    criteria: list[_SuggestedCriterion]
```

## LLM prompt

System prompt (in `criteria_suggester.py`):

> You are a recruiting expert. Given a job title and description, propose 3 to 6 weighted scoring criteria the recruiter can use to evaluate candidates. Each criterion needs:
> - `name`: short, ≤ 128 chars (e.g. "Java expertise")
> - `weight`: float in [0, 1]; weights across all criteria must sum to 1.0
> - `description`: one or two sentences explaining what evidence to look for
>
> Return JSON only, matching the schema. Avoid overlapping criteria. Avoid generic filler ("good communicator") unless the JD specifically emphasizes it.

User prompt: title + description, asked to return the structured object.

`temperature=0.2` (deterministic-ish but allows variation across reruns).

## Server-side normalization

After the LLM returns:

1. **Count clamp:**
   - If `len(criteria) < 3` or `> 6` → re-prompt once with explicit count instruction. If still off, `502`.
2. **Weight normalization:**
   - Compute `total = sum(weights)`.
   - If `abs(total - 1.0) < 0.001`, leave it (already valid).
   - Otherwise scale each weight by `1/total`, round to 2 decimals, push residual onto the largest weight so the final sum is exactly 1.0.
3. Validate against `CriteriaItem` (existing schema). If validation still fails, `502`.

This is intentionally conservative: the scorer comment in `pipeline/scorer.py` already states "weights sum to 1.0", so the suggestion endpoint must produce input that the scorer expects.

## Error handling

| Condition                                      | HTTP | UX                                     |
|------------------------------------------------|------|----------------------------------------|
| `description` < 50 chars                       | 400  | Button disabled (frontend gate)        |
| LLM call raises / network error                | 502  | Toast: "Couldn't suggest criteria — try again." |
| LLM returns invalid JSON or count off by ≥1 after re-prompt | 502 | Same toast |
| User cancels confirm dialog                    | n/a  | No-op, no API call wasted              |

`criteria` field-array is **never partially modified** — replace is atomic on success, untouched on any failure.

## Frontend changes

**File:** `recruiter-frontend/src/routes/jobs-new.tsx`

- Add `Sparkles` lucide icon to existing import line.
- Add `useState` for `suggesting: boolean` and `confirmOpen: boolean`.
- Watch the description field via `form.watch("description")` to enable/disable the button at the 50-char threshold.
- New `useMutation` `suggestCriteria` hitting the new endpoint.
- New button in the criteria header row:
  ```tsx
  <Button type="button" variant="outline" size="sm"
          disabled={(form.watch("description") ?? "").length < 50 || suggesting}
          onClick={onSuggest}>
    <Sparkles className="h-4 w-4 mr-1" />
    {suggesting ? "Suggesting…" : "Suggest from JD"}
  </Button>
  ```
- `onSuggest`: if `criteria.fields.length > 0` → open confirm dialog; else call mutation directly.
- On success: `criteria.replace(response.criteria)`.
- On error: `toast.error("Couldn't suggest criteria — try again.")`.

**Confirm dialog:** reuse the existing `Dialog`/`AlertDialog` primitive in `components/ui/`.

## Testing

### Backend (pytest)

- `tests/unit/pipeline/test_criteria_suggester.py`
  - Fake `LLMClient` returning a fixed 4-criterion payload → asserts pass-through.
  - Fake returning weights `[0.3, 0.3, 0.3, 0.3]` (sum 1.2) → asserts normalized to sum exactly 1.0.
  - Fake returning 2 criteria → triggers re-prompt; second response valid → succeeds.
  - Fake returning 2 then 2 again → raises (becomes `502` at API layer).
  - Asserts prompt includes both title and description.
- `tests/api/test_criteria_suggest_endpoint.py`
  - 200 happy path with mocked dependency override.
  - 400 if description short.
  - 502 if pipeline raises.
  - 401/403 same as other `/api/jobs/*` endpoints (auth gate).

### Frontend (vitest + msw)

- `jobs-new.test.tsx` (extend existing) or new `suggest-criteria.test.tsx`:
  - Button disabled when description has < 50 chars; enabled at 50.
  - Click on empty `criteria` → mocked msw returns 4 rows → field-array populates.
  - Click when `criteria.fields.length > 0` → confirm dialog renders; **Cancel** leaves rows; **Replace** overwrites with mocked rows.
  - msw 500 → error toast appears, criteria untouched.
  - Spinner / disabled state during pending.

### E2E (Playwright, optional)

- New `scripts/e2e-suggest-criteria.mjs`:
  - Goes to `/jobs/new`, fills title + description, clicks button, waits for ≥ 3 rows in the criteria field-array, asserts weights are numeric and sum ≈ 1.0.
  - Optional: add a row first, click again, dismiss confirm, assert original row still present.

## Open questions

None at design time. Implementation plan should pin:
- The exact HTTP status convention used elsewhere for LLM upstream errors (502 vs 503 vs 500) — check `api/applications.py` scoring path before settling.
- Whether the existing project has an `AlertDialog` primitive or only `Dialog` — picks the right confirm component.

## Risk notes

- **Cost:** each click is one LLM call (small JSON output, ~1–2k input tokens). At a flat rate it's negligible, but the description-length gate prevents accidental empty calls.
- **Quality:** the LLM might propose generic criteria for sparse JDs. The system prompt includes "avoid generic filler"; if quality is poor in practice, follow-up could add few-shot examples.
- **Trust:** the user retains full edit/remove control after suggestion, and the confirm-on-replace gate makes destructive changes deliberate.
