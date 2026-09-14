# Multiple interviewers

Date: 2026-09-14
Status: approved (design)
Builds on: `2026-09-10-interview-kits-design.md`, `2026-09-10-interview-kits-decisions.md`

## Problem

An interview kit today is one JSON blob per application: one list of
questions, one set of answers and ratings, one submit that moves the
candidate to `INTERVIEWED`. It assumes a single person interviews. In
practice a candidate is seen by two or three people — a recruiter, a
hiring manager, a senior engineer — and each needs to record what they
heard without overwriting the others, and the recruiter needs to read
the feedback side by side.

This feature adds interviewers as first-class assignments on an
application, gives each interviewer their own feedback sheet on the
shared kit, and moves the candidate to `INTERVIEWED` once every sheet is
in.

## Decisions taken during design

Recorded so the plan does not re-open them.

1. **Panel feedback, not rounds.** Several people interview the same
   candidate and each records their own answers and ratings. Multiple
   rounds with different question sets are a later slice on top of this.
2. **One kit, many sheets.** The questions are generated once and shared
   by every interviewer on the candidate; only answers, ratings and the
   verdict are per person. A kit per interviewer would cost an LLM call
   per person, produce nothing comparable across people, and make
   "submit" ambiguous.
3. **Interviewers are existing user accounts.** No tokens, no public
   page. Anyone who interviews logs in.
4. **Any active user can be assigned, viewers included.** A viewer
   assigned to a candidate may write exactly one thing: their own sheet
   on that candidate. This is the one deliberate exception to the viewer
   read-only policy.
5. **The stage advances automatically** when every assigned interviewer
   has submitted. The recruiter's existing "Mark as interviewed" action
   remains as the override for a no-show.
6. **Feedback is blind until submitted.** An interviewer sees only their
   own sheet until they submit; then they see everyone's. Recruiters and
   admins always see all.
7. **Storage is a new assignments table**, questions stay in the kit
   JSON. Each interviewer writes their own row, so concurrent saves do
   not race; the viewer exception is a row lookup; "my interviews" is a
   plain query.
8. **Legacy per-question answers are read, never written again.** The
   `answer` and `rating` fields on kit questions, and the kit's
   `submitted_at`, stay in the schema so no data migration is needed.
   They render read-only when present and the code path disappears once
   no kit carries them.

## What it is not

Deliberately excluded, each a coherent follow-up on its own:

- **Emailing or calendar-inviting interviewers** when assigned. The
  notify flow addresses the candidate; interviewer scheduling is a
  separate design.
- **Multiple rounds** (technical, HR) with distinct question sets.
- **Per-question interviewer tagging** ("A asks the technical ones").
  The shared list already allows split panels by leaving questions
  blank; steering that is a later slice.
- **Feeding verdicts or ratings into the 0–100 score.** Still advisory.
- **External interviewers without accounts.**

## Data model

### New table `interview_assignments`

| Column | Type | Notes |
|---|---|---|
| `id` | integer | primary key |
| `application_id` | integer | FK `applications.id`, `ON DELETE CASCADE` |
| `user_id` | integer | FK `users.id`, `ON DELETE CASCADE` |
| `sheet` | JSON, not null | see below; `{}`-equivalent default on create |
| `submitted_at` | timestamptz, nullable | null until the interviewer submits |
| `created_at` | timestamptz, not null | `now()` |
| `updated_at` | timestamptz, not null | `now()`, updated on write |

Unique constraint on `(application_id, user_id)`. One row is one
interviewer on one candidate. Assigning creates the row with an empty
sheet; saving edits the sheet in place; submitting stamps
`submitted_at`, after which the sheet is frozen.

`sheet` is:

```json
{
  "answers": {
    "<question_id>": { "answer": "string | null", "rating": "strong | adequate | weak | null" }
  },
  "verdict": { "decision": "hire | no_hire | unsure | null", "note": "string | null" }
}
```

Answers are keyed by question id, so a renamed question keeps its
ratings and a removed question drops its answers on every sheet at once.
`rating` reuses the existing `Rating` enum. Free-text limits match the
current kit: 20 000 characters per answer, 2 000 for the verdict note.

### Changes to the kit JSON (`applications.interview_kit`)

Two additions:

- A question gains an optional `added_by: int | null` — the user id of
  an interviewer who appended it. Generated and recruiter-authored
  questions carry `null`.
- The kit gains `closed_at: iso-8601 | null`, set when the candidate
  moves to `INTERVIEWED` by either the automatic rule or the manual
  override.

Legacy fields kept but no longer written: the kit's `submitted_at`, and
each question's `answer` and `rating`.

### Question freeze

Once any assignment on the application has `submitted_at` set, the
question list is frozen: removal, reordering that drops ids, and
regeneration are refused with 409. Appending remains allowed. Without
this, submitted feedback would silently lose rows.

## API and permissions

All routes live in `api/interview.py` beside the existing kit routes.
Roles: **R/A** = recruiter or admin, **any** = every authenticated role.

### Assignments

`GET /api/applications/{id}/interviewers` — any.
Returns `[{user_id, name, email, submitted_at}]`, ordered by assignment
time.

`PUT /api/applications/{id}/interviewers` — R/A.
Body `{"user_ids": [int]}`. Reconciles: creates rows for new ids, deletes
rows for ids no longer listed. Refuses with 409 if a row to delete has
`submitted_at` set — feedback cannot vanish by unticking a name. Refuses
with 422 for an unknown or inactive user. Idempotent.

### Sheets

`GET /api/applications/{id}/interview-kit` — any (exists today).
Gains a `sheets` list, filtered per the visibility table below. Each
entry is `{user_id, name, sheet, submitted_at}`.

`PATCH /api/applications/{id}/interview-kit/sheet` — any, own sheet only.
Body is a full `sheet` object. 404 if the caller has no assignment on
this application. 409 if the caller's sheet is submitted. Answers for
question ids not in the kit are dropped on save, not rejected, so a
concurrent question removal does not turn a save into an error.

`POST /api/applications/{id}/interview-kit/sheet/submit` — any, own
sheet only. Stamps `submitted_at`, then applies the stage rule. 404 and
409 as for PATCH.

**Recruiter with no assignments.** If a recruiter or admin saves or
submits a sheet on an application with no assignment rows, one is
created for them on the spot. This is what keeps the single-recruiter
flow working with zero setup, exactly as it does today.

### Questions

`PATCH /api/applications/{id}/interview-kit` (exists today) keeps
editing the question list, with two changes: it refuses removals and
id-dropping reorders with 409 once the list is frozen, and an assigned
interviewer may call it to **append** questions only — any other change
from an interviewer is 403. Appended questions get `added_by` set to the
caller. `generate` is refused with 409 once frozen. `draft-question` is
unchanged and available to assigned interviewers.

### Viewer exception

The two sheet routes and the kit PATCH are added to
`VIEWER_ALLOWED_ROUTES` in `api/permissions.py`. The allow list is per
route, so the append-only restriction on the kit PATCH is enforced by
its handler, not by the guard. Each handler checks the assignment row
itself, so a viewer can only write a sheet that exists for them. The module docstring
gets a paragraph explaining the exception the way chat is explained
there: allow-listing the route without the row check would let any
viewer write feedback on any candidate.

The chat agent's kit read tool applies the same visibility filter as the
kit GET, keyed on the chatting user, so a viewer cannot read hidden
sheets by asking the agent.

## Stage and visibility rules

### Moving to `INTERVIEWED`

On every sheet submit, in the same transaction:

1. If the application is not in `SCHEDULED`, do nothing to the stage.
   Re-submitting from `INTERVIEWED` or later never moves the candidate
   (the guard that exists today).
2. Otherwise, if every assignment on the application has `submitted_at`
   set, move the stage to `INTERVIEWED`, stamp `interviewed_at`, and set
   the kit's `closed_at`.

With no assignments, the submitter's just-created row is the only one,
so their submit moves the candidate: today's behaviour, preserved.

The existing manual move to `INTERVIEWED` (`PATCH /applications/{id}`
with `stage`) also sets `closed_at`. Unsubmitted sheets stay editable
after that, so a late interviewer can still record feedback; their
submit then hits rule 1 and does not move the stage again.

### Who sees which sheets

| Caller | Before own submit | After own submit |
|---|---|---|
| Recruiter or admin | all sheets | all sheets |
| Assigned interviewer (any role) | own sheet only | all sheets |
| Unassigned viewer | no sheets | no sheets |

The kanban card shows `n/m sheets in` while the application is in
`SCHEDULED` and has at least one assignment.

### Events

Assignment changes and sheet submissions publish on the existing
`interview_kit` SSE event (`api/events.py`), so open pages refresh the
way they already do for generation. Sheet *saves* do not publish; they
are private until submitted.

## Generation

Unchanged. One LLM call per candidate, triggered automatically on entry
to `SCHEDULED` or manually by a recruiter or admin. Inputs are the job's
criteria, its baseline questions and the candidate's profile;
interviewers are not an input. Interviewers cannot regenerate; they can
draft and append single questions.

## UI

### Interviewers picker

On the candidate page, on the stage line above the tabs: an
"Interviewers" chip list. Each chip is the user's name, with a tick once
they have submitted. Recruiters and admins see an "Assign" button that
opens a dialog listing active users (name and email) with checkboxes
and a search box; saving calls the reconcile endpoint. Viewers see the
chips only.

### Interview Kit tab — interviewer view

The existing tab with three changes:

- The answer box and rating buttons write to the caller's sheet.
- A verdict block under the questions: three toggle buttons
  (Hire / No hire / Unsure) and a short note field.
- "Save answers" saves the sheet; "Submit interview" submits it and
  renders the sheet read-only. The `window.confirm` on the
  unanswered-questions path is replaced by a real dialog — follow-up 4
  from the decisions doc, done here because that path now needs tests.

An interviewer gets "Add question" (typed or AI-drafted) and nothing
else on the question list.

### Interview Kit tab — recruiter and admin view

The interviewer view plus a **Feedback** section under the questions,
shown only when more than one sheet exists. A table: one row per
question, one column per interviewer; each cell is the rating as a
coloured pill, with the answer revealed on expand. A verdict row sits at
the top. Questions with no rating on any sheet are collapsed by default.

Question editing, removal, AI drafting and regenerate remain recruiter
and admin only, and are disabled with a tooltip once the list is
frozen.

### Legacy answers

If a kit still carries per-question `answer`/`rating` values, they
render read-only under a small "Recorded before interviewer sheets"
note. No control writes to them.

### Kanban card

`n/m sheets in` under the stage label, only while `SCHEDULED` with
assignments.

## Testing

### Backend (pytest, real Postgres via testcontainers, as the API tests do)

- **Assignments**: reconcile adds and removes; 409 on removing a
  submitted sheet; 422 on an inactive or unknown user; rows cascade on
  application delete and on user delete.
- **Sheets**: save then read back; 404 for an unassigned caller; 409 on
  a second submit; a recruiter with no assignments gets a row created on
  first save; answers for unknown question ids are dropped on save.
- **Visibility**: one test per row of the table, plus the chat agent's
  kit read tool applying the same filter.
- **Stage rule**: two interviewers, first submit leaves `SCHEDULED`,
  second moves to `INTERVIEWED` and sets `closed_at` and
  `interviewed_at`; no-assignment submit moves it; manual move then a
  late submit does not move it again; submit from `OFFER` never moves
  it (closes decisions-doc follow-up 6).
- **Question freeze**: regenerate and removal 409 after the first
  submit; append with `added_by` allowed for an assigned interviewer;
  any other interviewer edit 403.
- **Viewer exception**: an assigned viewer can write their own sheet,
  cannot write another's, cannot write on an unassigned candidate, and
  still gets 403 on every other mutating route.

### Frontend (vitest)

Picker reconciles; interviewer view saves and submits a sheet; verdict
block; feedback table renders one column per sheet and collapses
unrated questions; freeze disables question controls; legacy answers
render read-only; kanban card shows `n/m sheets in`.

### End to end (Playwright)

Extend `e2e/interview-kit.spec.ts`: create a second user through the
users API in the spec's own fixture, assign both, submit the first sheet
and assert the stage is still `SCHEDULED`, submit the second and assert
`INTERVIEWED`. The spec already seeds its own job and candidate.

## Migration and rollout

One Alembic revision adding `interview_assignments`. No data migration,
per decision 8.

Order, each step landing green on its own:

1. Migration, model, schemas.
2. Assignments API and reconcile.
3. Sheets API, visibility filter, stage rule, question freeze, viewer
   exception, agent tool filter.
4. Frontend: picker, interviewer view, verdict, feedback table, legacy
   rendering, kanban badge, confirm dialog.
5. End-to-end spec extension.

## Risks

- **A viewer exception is a policy change.** The default-deny guard
  exists so nothing ships open by accident; this opens two routes on
  purpose. The row check inside each handler is what makes it safe, and
  the viewer tests are the ones not to skip.
- **Freezing questions on first submit will surprise a recruiter** who
  wants to fix a typo after one interview. Renaming stays allowed
  (ids are stable); only removal and regenerate are refused, with a
  tooltip saying why.
- **Blind feedback relies on the filter being applied everywhere the kit
  is read** — the GET, the SSE payload, and the agent tool. The SSE
  event carries no sheet data, only a signal to refetch, so the filter
  lives in one place.
