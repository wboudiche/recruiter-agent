# Interview kits become rows

Date: 2026-09-20
Status: approved (design)
Builds on: `2026-09-14-multi-interviewer-design.md`,
`2026-09-14-multi-interviewer-decisions.md`
Phase 1 of: multiple kinds of interview kit (technical, RH, others)

## Problem

A job is interviewed in more than one way. A technical conversation and
an RH screen ask different questions, are run by different people, and
sometimes happen at different times — sometimes at the same time. Today
neither is expressible: an application has exactly one question list,
stored as a JSON blob on `applications.interview_kit`, shared by every
round and every interviewer.

The blob is also now actively in the way. Rounds landed on 2026-09-20
sharing that single question list, which forced the question freeze to
span every round: round one's submitted answers are keyed to ids that a
regeneration in round two would mint afresh, so regeneration had to be
refused globally. The consequence is that **once any sheet in round one
is submitted, round two can never regenerate its questions** — it
inherits round one's, appendable but not replaceable. That is a direct
cost of one shared blob, not a deliberate rule.

This phase moves kits out of the blob and into their own table, keyed by
`(application, round, track)`. It changes no behaviour a user can see.
It exists to make the phases after it cheap, and it removes the freeze
special case on the way.

## What this phase is not

- **Not templates.** Reusable org-wide question sets are phase 2.
- **Not parallel tracks.** The `track` column lands, but every value is
  `'default'` until phase 3.
- **Not generator modes.** RH-flavoured probes are phase 4.
- **Not a UI change.** The kit section, the panel picker and the
  feedback table render exactly as they do today.

## Decisions taken during design

Recorded so the plan does not re-open them.

1. **A kit is a row, not a blob.** Keyed `(application_id, round,
   track)`. Per-kit `status`, `error`, `generated_at`,
   `generating_since` and `closed_at` become columns rather than fields
   squeezed into shared JSON.
2. **`track` lands in this phase even though nothing varies it.** It is
   part of the unique constraint; adding it in phase 3 would mean
   rebuilding that constraint twice and migrating assignment rows again.
   Every row is `'default'` until phase 3.
3. **The freeze reverts to per-kit.** `is_frozen` stops spanning rounds.
   Each kit owns its question ids, so a regeneration in round two cannot
   orphan round one's answers. This deletes the global special case and
   fixes the round-two regeneration limitation described above.
4. **Round completion still spans tracks.** `close_round_if_complete`
   keeps working on the round, not the kit — with one track today this
   is unchanged, and phase 3 extends it to "every track in the round".
5. **The legacy per-question `answer`/`rating` fields move with the
   questions.** They are still read for kits recorded before answers
   moved onto sheets, and this phase does not change that.
6. **`applications.interview_kit` is dropped, not left in place.** Two
   sources of truth for the same data invites drift; the migration moves
   it and removes it in one step.
7. **The ORM model is `InterviewKitRow`, not `InterviewKit`.**
   `InterviewKit` is already the Pydantic schema in
   `schemas/interview.py`, and `api/interview.py` imports it — the
   module that would also import the model. The schema keeps its name
   and its job as the API read shape; the row gets the suffix. Renaming
   the schema instead would churn every call site to save one suffix.
8. **`kit_for` reads, it does not create.** It returns `None` when no
   kit exists, and creation stays explicit at the three points that
   mean it: first entry to `scheduled`, opening the next round, and
   `generate` on an application that has no kit yet (which is how the
   "Generate interview kit" button works today and must keep working).

## Data model

### New: `interview_kits`

| column | type | notes |
|---|---|---|
| `id` | int PK | |
| `application_id` | FK → `applications` ON DELETE CASCADE | |
| `round` | int NOT NULL | matches `applications.interview_round` for the live round |
| `track` | str NOT NULL DEFAULT `'default'` | phase 3 varies this |
| `questions` | JSON NOT NULL | the list currently in the blob |
| `status` | str NOT NULL | `generating` / `ready` / `error` |
| `error` | str NULL | |
| `generated_at` | str NULL | ISO-8601, as today |
| `generating_since` | str NULL | drives the idempotency guard |
| `closed_at` | str NULL | set when the round closes |
| `created_at` / `updated_at` | timestamptz NOT NULL | |

`UNIQUE (application_id, round, track)`, plus an index on
`application_id`.

### Changed: `interview_assignments`

Gains `track` (str NOT NULL DEFAULT `'default'`). Its unique constraint
becomes `(application_id, user_id, round, track)`. A sheet belongs to
exactly one kit, found by `(application_id, round, track)`.

### Removed: `applications.interview_kit`

Dropped after the migration copies it out.

## Migration

Forward, per application with a non-null `interview_kit`:

- Insert one `interview_kits` row **for every round from 1 to
  `applications.interview_round`**, each carrying a copy of the blob's
  questions and its `status` / `error` / `generated_at` / `closed_at`.
- `track` is `'default'` throughout.

The per-round copy is not redundancy for its own sake. An application
reopened into round two has one shared kit today, and round one's
submitted sheets resolve their answers against its question ids. Writing
a single row at the live round would leave round one's feedback pointing
at a kit that does not exist, and the feedback table would render empty
cells for a closed round. Rounds shipped days ago, so this may affect
zero rows in production — the migration has to be correct regardless.

Backward: collapse each application's kits to the one at the highest
round, write it back into `applications.interview_kit`, drop the table
and the `track` column. Rows for earlier rounds are discarded, which is
lossless in practice because they are copies.

## Code changes

Thirty references to `app_row.interview_kit` across six backend modules
(`models/application.py`, `api/applications.py`, `api/interview.py`,
`api/interviewers.py`, `pipeline/interview_sheets.py`,
`models/interview_assignment.py`). Each becomes a lookup of the kit for
`(application, current round, 'default')`.

A single accessor carries that lookup so the tuple is spelled once:

```python
async def kit_for(session, app_row, *, track="default") -> InterviewKitRow | None
```

Returns `None` rather than creating — see decision 8.

Rules that move from "the blob" to "this kit":

- `is_frozen(rows)` → takes the rows of one kit, not the application.
- `answered_question_ids` → unchanged; callers pass one kit's rows.
- `generation_in_flight` → reads the kit row's `generating_since`.
- `close_round_if_complete` → still round-scoped; reads the round's kit
  for `closed_at`.
- `_open_next_round` → creates the next round's kit as a copy of the
  previous round's questions, rather than clearing `closed_at` on a
  shared blob. Regeneration in the new round is then legal.

## Testing

The phase's main correctness signal is that **the existing kit, freeze,
sheet, panel and rounds tests pass unchanged**. Any test that has to
change is a behaviour change, and each one must be justified in the PR
rather than adjusted quietly.

New tests:

1. The migration creates one kit per round for a reopened application,
   and round one's sheet still resolves its answers afterwards.
2. The migration's backward path restores a single blob and drops the
   table.
3. A submitted sheet in round one no longer blocks regeneration in round
   two — the limitation this phase fixes, asserted directly.
4. The freeze still refuses removal and regeneration *within* a kit.
5. `generation_in_flight` reads the row, so a double generate is still a
   no-op and a stale one is still retryable.
6. A kit row is created on first entry to `scheduled`, and reopening
   creates the next round's row rather than mutating the first.
7. `generate` on an application with no kit at all creates one, so the
   "Generate interview kit" button still works from a standing start.

## Risks

- **A 30-reference refactor with no behaviour change is exactly where a
  silent regression hides.** The mitigation is the unchanged-tests rule
  above, and reviewing the diff for any test whose expectations moved.
- **The backward migration is lossy for multi-round applications.**
  Acceptable because the discarded rows are copies, but it means a
  downgrade after a phase-3 deploy — where tracks genuinely differ —
  would lose data. Phase 3 must revisit its own downgrade rather than
  inherit this one.
- **`track` is dead weight until phase 3.** Deliberate, per decision 2;
  the cost of adding it later is a second constraint rebuild.

## Where this is going

- **Phase 2 — templates.** Org-wide reusable question sets, each with
  its own generator voice and input allowlist, snapshotted into a kit at
  creation so editing a template never rewrites a closed kit.
- **Phase 3 — tracks.** Parallel panels within one round; the round
  closes when every track's sheets are in.
- **Phase 4 — generator modes.** Probes drawn from profile and
  enrichment for RH-style templates, from the score breakdown for
  technical ones.
