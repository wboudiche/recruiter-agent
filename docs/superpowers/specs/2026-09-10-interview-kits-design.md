# Interview kits

Date: 2026-09-10
Status: approved (design)

## Problem

The pipeline scores a candidate, and then stops helping. Between
`SCHEDULED` and `INTERVIEWED` the recruiter is on their own: they know the
candidate scored 57, they can read the per-criterion rationales, and then
they open a blank notes field and improvise an interview.

That is a waste of the most useful thing the system already knows. The
scorer writes sentences like *"Docker/Kubernetes listed, but no clear
evidence of managing production-grade clusters"* — which is not a score,
it is a question. It names the doubt the interview exists to resolve.

This feature turns those rationales into an interview kit: generated
questions the recruiter edits before the call, answers and ratings
recorded during it.

## What it is not

Deliberately excluded, each a coherent follow-up on its own:

- **Sending questions to the candidate.** No public pages, no tokens, no
  email. The kit lives behind the recruiter's login.
- **Feeding ratings into the 0–100 score.** Interview ratings stay
  advisory. Mixing interview evidence into the CV-derived score needs
  rules for weighting and re-interviews that nothing yet demands.
- **Cross-candidate reporting.** "Show everyone rated weak on Kubernetes"
  is a real want, and the reason to revisit storage (see *Storage
  trade-off*). It is not built now.
- **Export or print**, and a **reusable question library**.

## Data model

Two JSON columns, matching how the repo already stores structured data
that is read whole and never queried by field: `jobs.criteria`,
`applications.score_breakdown`, `applications.enrichment`.

```
jobs.interview_baseline    JSON | None
applications.interview_kit JSON | None
```

`interview_baseline` is a list of `{id, text, criterion?}` — the questions
every candidate for this role should answer, edited on the job.

`interview_kit` is:

```json
{
  "status": "generating" | "ready" | "error",
  "error": "string, present only when status is error",
  "generated_at": "iso-8601",
  "submitted_at": "iso-8601 | null",
  "questions": [
    {
      "id": "q1",
      "text": "Walk me through a production Kubernetes cluster you owned.",
      "source": "baseline" | "probe",
      "criterion": "Kubernetes & containers",
      "answer": "string | null",
      "rating": "strong" | "adequate" | "weak" | null
    }
  ]
}
```

`id` is an opaque string, unique within a kit. The server assigns ids when
it generates questions; questions added through `PATCH` may carry
client-generated ids, and the server rejects a payload containing
duplicates.

`criterion` is optional and advisory — it links a question back to the
criterion that motivated it, so the recruiter can see *why* they are
asking. Nothing enforces that it matches a live criterion name, because
criteria can be edited after a kit is generated and an interview record
must not break when they are.

### Merge rule

At generation the kit's `questions` array is:

1. a **snapshot** of `job.interview_baseline`, in order, each
   `source: "baseline"`, then
2. the generated candidate-specific questions, each `source: "probe"`.

Both directions are one-way and deliberate:

- Editing the job baseline later does **not** rewrite existing kits. An
  interview record is evidence of what was actually asked. This mirrors
  `score_breakdown`, which freezes the criteria that produced it.
- Editing a question inside a kit does **not** write back to the job
  baseline. Tailoring one interview must not silently change the role's
  standard questions.

### Storage trade-off

JSON is right for today and wrong for one specific future. A shared
per-job baseline exists partly so candidates are comparable, and real
comparison eventually means querying — which SQL does and a JSON blob does
not, not without pain.

The trigger to normalise into `job_questions` / `interview_answers` tables
is a cross-candidate reporting requirement. Until then two tables, two
migrations, cascade rules and an ordering column buy nothing: a job's kits
can be loaded and compared in the application at these volumes.

## Generation

`pipeline/interview_kit_generator.py`, following `criteria_suggester.py`
and `query_suggester.py`: one structured-output call returning
`GeneratedQuestions` from a new `schemas/interview.py`.

The prompt receives the candidate profile, the job criteria, **the score
breakdown rationales**, and the baseline questions. The rationales are the
point — they already state each doubt in prose. The baseline is included
so probes do not duplicate questions the recruiter is asking anyway.

`max_tokens=2048`, not 512. A reasoning model spends that budget thinking
before it writes anything, and 512 is what made query suggestion fail
intermittently with null content (`fix(llm)`, PR #17).

## Stage wiring

The kit is wired into the finite-state machine in both directions, with
one hard constraint: **an LLM call must never be able to break a stage
transition.** Two PRs hardened that FSM this year; a generation failure
must not leave a candidate stuck between stages.

**Entering `SCHEDULED`** sets `interview_kit = {"status": "generating"}`,
**commits**, and only then enqueues the work with
`background_tasks.add_task` — the shape `/re-enrich` already uses
(`api/applications.py:433`). The stage move is durable before any model is
called. Progress publishes on the existing bus as
`{"type": "interview_kit", "application_id": id, "status": ...}`, so the
panel updates over SSE exactly as stage changes already do.

**Submitting** sets `submitted_at` and advances `SCHEDULED → INTERVIEWED`,
setting `interviewed_at`. If the candidate is already `INTERVIEWED` or
beyond, no stage change occurs — so editing and re-submitting after the
interview is safe, and a re-interview never double-advances.

Unanswered questions produce a client-side warning, not a block. Real
interviews get cut short, and refusing to submit would only encourage
invented answers.

## API

A new `api/interview.py`, rather than growing `api/applications.py`
further.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/applications/{id}/interview-kit` | Read the kit |
| `POST` | `/api/applications/{id}/interview-kit/generate` | Generate or retry; returns 202 |
| `PATCH` | `/api/applications/{id}/interview-kit` | Edits, answers, ratings, add, delete |
| `POST` | `/api/applications/{id}/interview-kit/submit` | Record and advance the stage |
| `PUT` | `/api/jobs/{id}/interview-baseline` | Edit the role's shared questions |

`PATCH` replaces the `questions` array wholesale — the simplest contract
against JSON storage, last write wins. One recruiter conducts one
interview; locking would be machinery for a conflict that does not occur.

Writes require the recruiter role, following the viewer permission matrix
(`2026-08-15-viewer-permission-matrix-design.md`). Reads are open to
viewers: a hiring manager should be able to read what was asked.

## Regeneration preserves answers

Regenerating replaces only questions whose `answer` is null. Any question
already answered is kept exactly as it is, whatever its source.

Unanswered **baseline** questions are re-snapshotted from the job's current
baseline, and unanswered probes are regenerated. This does not contradict
the merge rule above: that rule prevents *passive* drift, where editing a
job silently rewrites interviews nobody touched. Regeneration is an
explicit act on one kit, and someone who asks for it should get the
questions the role asks today.

Losing typed interview notes to a stray Retry click is the same class of
mistake as the credential-clearing bugs in PR #18 — a destructive action
reachable from a control that looks harmless. The safe behaviour is the
default, and it is tested.

## UI

`components/candidate/interview-kit-section.tsx`, on the application
detail page beside `enrichment-section.tsx`, with four states:

- **absent** — a *Generate interview kit* button
- **generating** — a loader, driven by SSE
- **error** — the message plus *Retry*
- **ready** — the question list

Each question row carries inline-editable text, a source badge (*Role* or
*For this candidate*), an answer textarea, a three-way rating control, and
delete. Below the list: *Add question* and *Submit interview*, the latter
confirming when questions are unanswered.

The job baseline is edited in its own sheet on the job page, modelled on
the existing `edit-criteria-sheet.tsx` — same interaction, same shape, so
it needs no new vocabulary.

Write controls gate on `canWrite`, as `EnrichmentSection` and `ActionBar`
already do.

## Testing

**Backend.** The generator against `FakeLLMClient`. API tests for
generate, patch and submit. A test that a *failing* generation leaves the
candidate correctly in `SCHEDULED` — the constraint the whole stage design
exists to protect. A test that submit advances once and only once. A test
that regeneration preserves answered questions.

**Frontend.** The four states; editing a question; setting a rating; the
unanswered-submit warning; `canWrite` gating.

**E2E.** Generate, edit, answer, submit, and assert the candidate shows as
Interviewed — in the suite that now shares a single login
(`e2e/auth.setup.ts`).

## Risks

**The questions could be bland.** The feature is only worth having if the
probes are sharper than what a recruiter would write unaided. The
mitigation is feeding the score rationales rather than the raw profile,
but this is a quality question that tests cannot answer — it needs a human
reading real output on real candidates before the feature is called done.

**Baseline drift.** Because kits snapshot, a job whose baseline changes
often will accumulate kits asking different questions. That is correct
behaviour, but it will look like inconsistency to anyone comparing two
old interviews. Worth surfacing in the UI later — a "generated from an
older baseline" note — not worth building now.
