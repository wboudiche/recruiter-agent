# Interview tracks

Date: 2026-09-22
Status: approved (design)
Builds on: `2026-09-20-interview-kits-as-rows-design.md` (phase 1),
`2026-09-21-interview-templates-design.md` (phase 2)
Phase 3 of: multiple kinds of interview kit (technical, RH, others)

## Problem

Phase 2 lets each round use a template, so a technical round can be
followed by an RH round. Some hiring runs them **at the same time**
instead: a technical conversation and an RH screen on the same day, with
different interviewers, different questions and separate verdicts. Today
a round holds exactly one kit and one panel, so running both in parallel
means either merging them into one template (one shared question list,
one blended panel) or stretching them over two rounds (the candidate
waits for a round to close before the second interview can be recorded).

This phase lets a round hold several **tracks**, one per template. Each
track has its own questions, its own panel and its own sheets, and the
round closes when every track is done.

## What this phase is not

- **Not profile-driven probes.** RH tracks still use `probe_mode: none`
  or `score_gaps`; drawing probes from career history is phase 4.
- **Not a scheduling tool.** Tracks have no dates or rooms; "parallel"
  means both are recorded against the same round.
- **Not per-track stages.** The application still has one stage. A track
  is "done" when its panel has submitted, not when it reaches a stage.

## Decisions taken during design

Recorded so the plan does not re-open them.

1. **The kit is the track.** A track is one `interview_kits` row plus the
   `interview_assignments` rows sharing its `(application, round, track)`.
   No new table: phase 1 put `track` into both tables' keys for this.
2. **Tracks are chosen at round start, and can be added later.** The
   round-start picker becomes multi-select (one track per ticked
   template, plus "No template"). While the application is *scheduled*, a
   recruiter can add a track; a track can be removed only while nobody on
   it has written anything, and never if it is the round's last.
3. **Interviewers see only their own track.** Their track's questions,
   their own sheet, and after submitting, that track's other submitted
   sheets — the phase-1 blind rule, scoped to the track instead of the
   round. Recruiters and admins see every round and every track.
4. **One track per interviewer per round.** A person is on at most one
   track in a round. Someone who genuinely runs both conversations runs
   one track with a combined template.
5. **The track key is derived from the template at creation and never
   changes:** `t<template_id>` for a templated track, `default` for the
   no-template track. The existing unique key `(application_id, round,
   track)` therefore enforces one track per template per round and at
   most one no-template track per round.
6. **A kit's template never changes after creation.** Choosing a
   different template means a different track. This replaces phase 2's
   same-round restamp.
7. **Freeze and answered-question protection are per track.** A submitted
   RH sheet freezes only the RH track's questions.
8. **The round closes when every track has at least one interviewer and
   every interviewer in the round has submitted.** An unstaffed track
   blocks the automatic close, so an RH track nobody was assigned to
   cannot be silently skipped when the technical panel finishes. "Mark
   as interviewed" still closes the whole round by hand.
9. **"Another round" preselects the previous round's tracks** (those
   whose templates are still active). First scheduling still preselects
   the job's default. The job keeps a single default template.
10. **One-track rounds behave and look exactly as today.** Every API that
    gains a track parameter defaults to the round's only track, and the
    UI adds tabs and track labels only when a round has two or more.

## Data model

No new tables.

### `interview_kits`

Unchanged schema. The `track` value follows decision 5 for every kit
created from now on.

### `interview_assignments`

The unique constraint `uq_interview_assignment_app_user_round_track`
`(application_id, user_id, round, track)` is replaced by
`uq_interview_assignment_app_user_round` `(application_id, user_id,
round)` — decision 4. Every existing row has track `default`, so no
existing data can violate it.

### Migration

One migration:

1. Re-key phase-2 templated kits: for every `interview_kits` row with
   `template_id IS NOT NULL` and `track = 'default'`, set
   `track = 't' || template_id`, and set the same value on the
   `interview_assignments` rows with the same `(application_id, round)`
   and `track = 'default'`. Afterwards every kit's key follows decision 5.
2. Swap the assignment unique constraint as above.

Downgrade: refuse (raise) if any `(application_id, round)` has more than
one kit — pre-phase-3 code can only read one — otherwise re-key every kit
and assignment back to `default` and restore the old constraint.
Verified upgrade → downgrade → upgrade against real Postgres, as in
phases 1 and 2.

## Rules

Pure functions in `pipeline/interview_sheets.py` and
`pipeline/kit_store.py`, tested without a database where possible:

- `track_key(template_id: int | None) -> str` — decision 5.
- `rows_in_track(rows, round, track)` — alongside `rows_in_round`.
  `is_frozen`, `answered_question_ids` and the blind rule in
  `visible_sheets` are called with one track's rows.
- `round_complete(kits, rows) -> bool` — decision 8: every kit in the
  live round has at least one assignment in its track, and every
  assignment in the round is submitted.
- `kits_in_round(session, app_row) -> list[InterviewKitRow]`, ordered by
  creation (`id`); `kit_for(session, app_row, track=...)` stays for
  single-track reads.
- `resolve_track(kits, requested: str | None) -> InterviewKitRow` — the
  default-track rule for recruiter endpoints: `requested` if given (404
  if the round has no such track), otherwise the round's only kit, or 422
  "track required" when the round has several.

## API

### Reading

`GET /api/applications/{id}/interview-kit` returns:

- `tracks: [{track, template_id, template_name, kit}]` — every track of
  the live round the caller may see (decision 3), in creation order.
  Someone on no track of the live round (an unassigned viewer) sees
  every track, as before tracks existed;
- `sheets` — unchanged flat list; `SheetRead` gains `track` beside
  `round`;
- `kit` and `template_name` — kept for compatibility: the caller's own
  track if they are on one, otherwise the round's first track.

### Starting a round

`PATCH /api/applications/{id}` with `stage: "scheduled"` gains
`interview_template_ids: list[int | null]` — the ticked templates, `null`
being the no-template track. Phase 2's `interview_template_id` remains
as shorthand for a one-item list. Neither → the job's default, as today.
Both, an empty list, an unknown or archived id, or either field with any
other stage → 422. Duplicates are collapsed.

### Adding and removing tracks

- `POST /api/applications/{id}/interview-tracks` `{template_id: int | null}`
  — only while the application is *scheduled* (409 otherwise); the
  template must be active (422 otherwise); 409 if that track already
  exists. Creates the kit (status
  `generating`) and dispatches its generation. Returns the kit read.
- `DELETE /api/applications/{id}/interview-tracks/{track}` — only while
  the application is *scheduled* (409 otherwise, so a closed round's
  record never changes); 409 if any
  sheet on the track is submitted or has content, or if it is the
  round's last track; otherwise deletes the kit and its (empty)
  assignments, then re-checks round completion (decision 8). Returns the
  kit read.

Both are admin/recruiter only, under the application row lock.

### Track-scoped recruiter endpoints

`POST …/interview-kit/generate`, `PATCH …/interview-kit` (edit
questions), `POST …/interview-kit/draft-question`, and
`PUT /api/applications/{id}/interviewers` gain an optional `?track=`,
resolved with `resolve_track`. `PUT /interviewers?track=…` reconciles
only that track's panel and returns 409 if a named user is already on
another track in this round (decision 4). `GET /interviewers` rows gain
`track`.

### Interviewer sheet endpoints

`PATCH …/interview-kit/sheet` and `POST …/interview-kit/sheet/submit`
take no track: the caller's assignment names it. The phase-1 carve-out —
a recruiter with no panel in the round gets a row created on the spot —
keeps working for one-track rounds; with several tracks it needs
`?track=`, and 422 without it.

### Events

The `interview_kit` event gains `track`.

## Round lifecycle

**First scheduling.** Resolve the choice list (above); create one kit per
choice with `template_fields(...)` and key `track_key(...)`, each in
`generating`; after the commit, dispatch one `run_generate_kit` per
track. Phase 2's no-provider rule applies per track: a track whose
snapshot wants no probes is dispatched without a model; one that needs
probes gets its own "No LLM provider configured" error kit.

**Same round scheduled again** (reject → re-invite → schedule). For each
ticked template: its track frozen → keep its questions, recovering a
stuck `error`/`generating` kit to `ready`; not frozen → regenerate,
keeping answered questions, as today; absent → create and generate.
Existing tracks not ticked are removed, with their empty panel rows, if
nobody on them has written anything, and kept otherwise.

**Interviewers picked before the round had a kit.** Assigning a panel
before scheduling puts the rows on `default`. Whenever a round's tracks
are created or reconciled, panel rows on a track that has no kit join the
round's first track, so interviewers picked early are not stranded; the
recruiter can then move them per track.

**A round that never had a kit, reopened with no template,** keeps the
pre-track behaviour: the panel carries over and no kit is made.

**Another round.** For each ticked template: the previous round had a
track with that template (matched by `template_id`, with no-template
matching no-template) → copy its kit forward (questions, snapshot,
status, error) and that track's panel with empty sheets; otherwise → a
fresh kit, generated, with an empty panel. Previous-round tracks that
were not ticked stay in history.

**Closing.** After every submit, panel change and track removal:
`round_complete` → `mark_interviewed`, which now stamps `closed_at` on
every kit in the round. "Mark as interviewed" closes the round by hand
and stamps every kit.

**Generation.** `run_generate_kit(..., track=...)`. After the model call
and the row lock, it abandons if the round moved (phase 1) or if its
track's kit no longer exists (the track was removed meanwhile). The
in-flight check stays per kit.

**Concurrency.** Every track mutation — schedule, add, remove, panel,
submit — runs under the application row lock that phase 1 uses.

## UI

- **Round-start picker** (`ScheduleRoundDialog`): checkboxes — every
  active template plus "No template"; at least one required. First
  scheduling preselects the job's default; "Another round" preselects
  the previous round's tracks whose templates are still active. Still
  not shown when no active templates exist.
- **Kit section:** one-track rounds unchanged. Recruiters get "+ Add
  track" while *scheduled* (a dialog listing the templates not yet in
  the round). With two or more tracks, the kit becomes tabs, one per
  track, named by template ("No template" for `default`), each showing
  its status and submitted count ("2/3"); the tab content is today's kit
  view for that track. "Remove track" sits on the tab, disabled with the
  reason when anyone on it has written something or it is the last.
  Interviewers see only their track, without tabs; the header reads
  "Interview kit · RH screen".
- **Panel** (`InterviewersPicker`): stays near the action bar. One track:
  as today. Several: one line per track ("Technical: Alice, Bob · RH
  screen: Carol"), each editable; a person already on another track is
  shown disabled with "on RH screen".
- **Feedback table:** one per track, inside that track's view, showing
  the live round's sheets on that track with its own verdict tally. (The
  table has only ever shown the live round; earlier rounds stay in the
  API's `sheets` for recruiters, as today.)
- **Structure:** `interview-kit-section.tsx` (622 lines) is split: a
  per-track `TrackKitView` (questions + own sheet + feedback) and the
  section itself (tabs, add/remove track).

## Testing

1. `track_key`, `rows_in_track`, `round_complete` (including an unstaffed
   track blocking the close) and `resolve_track`, as pure functions.
2. Scheduling with two templates creates two kits keyed `t<id>`, each
   generated independently; a `none` track needs no provider while a
   `score_gaps` track errors on its own without one.
3. `interview_template_ids` validation: both fields, empty list,
   archived id, non-scheduled stage → 422; duplicates collapsed.
4. Add track: created and generated; duplicate → 409; not scheduled →
   409; archived template → 422. Remove track: content or submitted → 409; last track → 409;
   removing the only unstaffed track completes the round.
5. Panel: `PUT ?track=` touches only that track; a user on another
   track → 409; `?track` missing with several tracks → 422.
6. Freeze per track: a submitted RH sheet blocks regenerating RH but not
   Technical.
7. Visibility: an RH interviewer never sees Technical questions or
   sheets, before or after submitting; recruiters see both.
8. Closing: the round closes only when every track is staffed and every
   sheet is submitted; manual close stamps every kit.
9. Another round: same templates copy kits and panels per track; a new
   template seeds fresh with an empty panel; unticked tracks stay in
   history.
10. Same round scheduled again: reconcile adds, keeps frozen or written
    tracks, removes empty unticked ones.
11. A generation whose track was removed meanwhile abandons its write.
12. Every pre-existing test passes: one-track rounds behave as today.
13. Migration round trip on real Postgres, including the re-key of a
    phase-2 templated kit and the downgrade refusal with two tracks.
14. Frontend: multi-select picker preselection; tabs appear only with two
    or more tracks; add/remove track; the per-track panel greys out
    people on another track; interviewer sees one track without tabs.

## Risks

- **Two kits generating at once means two LLM calls** when both tracks
  use `score_gaps`. That is the point of separate tracks; RH tracks
  normally use `none`.
- **An unstaffed track blocks the automatic close.** Intended (decision
  8), but a recruiter who adds a track and forgets to staff it will see
  the round stay open; the track tab shows "no interviewers" and "Mark
  as interviewed" remains available.
- **The compatibility `kit` field is ambiguous with several tracks.** It
  exists so one-track clients and tests keep working; new UI reads
  `tracks`.
- **Downgrade is refused once any round has two tracks.** Rolling back
  after real multi-track use requires removing the extra tracks first.

## Where this is going

- **Phase 4 — profile probes.** `probe_mode` gains `profile`; RH tracks
  switch to it and get questions drawn from career history and
  enrichment instead of the score breakdown.
