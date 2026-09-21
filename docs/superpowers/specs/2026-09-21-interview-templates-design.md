# Interview templates

Date: 2026-09-21
Status: approved (design)
Builds on: `2026-09-20-interview-kits-as-rows-design.md` (phase 1)
Phase 2 of: multiple kinds of interview kit (technical, RH, others)

## Problem

A job is interviewed in more than one way. A technical conversation and an
RH screen ask different questions and are run by different people. Today
every kit is seeded from the same place — the job's own
`interview_baseline` — and every kit is topped up with probes generated
from the technical score breakdown. There is no way to run an RH round:
its questions would be the job's technical baseline, and the generator
would append probes like "Kubernetes scored 40 — tell me about a cluster
you ran" to an HR conversation.

Phase 1 moved kits into `interview_kits`, one row per
`(application, round, track)`. This phase adds **interview templates**:
org-wide, reusable question sets that decide what a round's kit contains
and whether it gets generated probes. A recruiter picks the template when
a round starts, so round one can be technical and round two an RH screen.

## What this phase is not

- **Not parallel tracks.** One kit per round, `track = 'default'`, as in
  phase 1. Running technical and RH at the same time is phase 3.
- **Not RH-tailored probes.** A template can switch probes off; drawing
  probes from career history and enrichment is phase 4.
- **Not per-job restrictions.** Every active template is offered for every
  job; a job only chooses a default.

## Decisions taken during design

Recorded so the plan does not re-open them.

1. **A round's template is chosen when the round starts** — on first
   scheduling and on reopening. The job's default is preselected. Rounds
   can be skipped, repeated or reordered freely.
2. **Templates are org-wide.** Defined once, reused by every job.
3. **A template sets its probe mode:** `score_gaps` (today's generator,
   driven by criteria and the score breakdown) or `none` (curated
   questions only, no LLM call). Phase 4 adds a third mode.
4. **A template decides whether the job's own questions are included**,
   via `include_job_questions`. A technical template appends the job's
   baseline, as today; an RH template does not, so an HR round never
   inherits technical questions.
5. **A job points at one optional default template.** No per-job allowed
   list: the picker offers every active template.
6. **A kit snapshots its template at creation.** Regeneration reads the
   snapshot, never the live template, so editing a template cannot
   rewrite an existing kit.
7. **No template means exactly today's behaviour** — the job's baseline
   plus score-gap probes. Every kit created before this phase has no
   template, and so does any round where the recruiter picks "No
   template".
8. **Template question ids are namespaced in the snapshot** as
   `t<template_id>-<question_id>`. The editor mints UUIDs, so a collision
   with a job baseline id needs a copied question rather than bad luck —
   but ids are client-supplied and the backend does not require UUIDs
   (existing tests use `b1`). Sheets key answers by question id, so a
   collision would silently merge two questions' answers; namespacing
   makes it structurally impossible. Job baseline ids are **not**
   rewritten: existing kits and sheets already reference them.
9. **Templates are archived, never deleted.** Kits keep their snapshot
   and a copy of the template's name, so history stays readable.
10. **Admins and recruiters manage templates; viewers cannot.** The same
    people who edit job baselines today. The new router inherits the
    existing viewer default-deny for mutating routes.

## Data model

### New: `interview_templates`

| column | type | notes |
|---|---|---|
| `id` | int PK | |
| `name` | str(128) NOT NULL | unique among **active** templates (partial unique index), so an archived name can be reused |
| `description` | str NULL | what this interview is for |
| `questions` | JSON NOT NULL DEFAULT `[]` | list of `{id, text, criterion?}` — the existing `BaselineQuestion` shape, validated the same way |
| `probe_mode` | str(16) NOT NULL DEFAULT `'score_gaps'` | `score_gaps` \| `none` |
| `include_job_questions` | bool NOT NULL DEFAULT true | |
| `is_active` | bool NOT NULL DEFAULT true | false = archived |
| `created_at` / `updated_at` | timestamptz NOT NULL | |

A new template defaults to technical behaviour (`score_gaps`, include on);
an RH screen is created by switching both off.

Template question ids are capped at **48 characters** on save, so a
namespaced id (`t` + template id + `-` + question id) always fits the
64-character limit `KitQuestion` enforces. Editor-minted UUIDs are 36.

### Changed: `jobs`

Gains `default_interview_template_id` — int NULL, FK →
`interview_templates.id` ON DELETE SET NULL. An archived default is
treated as no default: it is never preselected.

### Changed: `interview_kits`

| column | type | notes |
|---|---|---|
| `template_id` | int NULL | FK → `interview_templates.id` ON DELETE SET NULL |
| `template_name` | str(128) NULL | copy of the name at creation, for display after a rename or archive |
| `template_snapshot` | JSON NULL | `{questions, probe_mode, include_job_questions}` at creation; questions already namespaced |

All three are NULL for kits created before this phase and for rounds
started with "No template".

## How a kit is assembled

Two pure functions in `pipeline/interview_kit.py`, so the rule lives in
one place and is tested without a database:

```python
def fixed_questions(
    snapshot: TemplateSnapshot | None,
    job_baseline: list[BaselineQuestion],
) -> list[BaselineQuestion]: ...

def wants_probes(snapshot: TemplateSnapshot | None) -> bool: ...
```

| round's template | fixed questions | probes |
|---|---|---|
| none | job's baseline | score-gap |
| `include_job_questions` on, `score_gaps` | template questions, then job's baseline | score-gap |
| `include_job_questions` off, `none` | template questions only | none |

Template questions come first, then the job's, so a shared standard opens
the interview and the job-specific questions follow.

`run_generate_kit` reads the kit row's snapshot, builds the fixed
questions with `fixed_questions`, and calls `generate_probes` only when
`wants_probes` is true. With `none` there is no LLM call at all; the
background task still runs, so the kit passes through `generating` to
`ready` exactly like any other and no new code path is needed for
status, freezing or merging.

## Starting a round

`PATCH /api/applications/{id}` gains an optional
`interview_template_id: int | null`, meaningful only with
`stage: "scheduled"`:

- **absent** → the job's default, if it exists and is active; otherwise
  no template;
- **`null`** → no template;
- **an id** → that template, which must exist and be active (422
  otherwise).

Sent with any other stage it is a 422, not silently ignored. Absent and
explicit `null` are told apart with Pydantic's `model_fields_set`.

**First scheduling** creates the round's kit with the chosen template's
snapshot, then generates as today.

**Reopening** keeps phase 1's copy-forward when nothing changes and seeds
fresh when something does:

- same template as the closing round (including none → none) — copy the
  previous kit's questions forward, exactly as today, **together with its
  snapshot, `template_id` and `template_name`**. "Same" compares
  `template_id`. Copying the snapshot rather than re-reading the template
  keeps decision 6 intact: if the template was edited between rounds, the
  follow-up round still regenerates from what the first round was built
  on;
- a different template — create the new round's kit from the new
  template's snapshot and generate it. Copying round one's technical
  questions into an RH round would be the pollution this phase exists to
  remove.

## API

- `GET /api/interview-templates?include_archived=false`
- `POST /api/interview-templates`
- `PATCH /api/interview-templates/{id}` — any of `name`, `description`,
  `questions`, `probe_mode`, `include_job_questions`, `is_active`
  (setting `is_active: false` archives)
- `JobRead` / job update gain `default_interview_template_id`
- The kit read gains `template_name`, so the section header can say which
  interview this is

Duplicate question ids within one template → 422, as the job baseline
endpoint already does.

## UI

- **Settings → Interview templates** — a new tab: list with archived
  toggle; create and edit in a sheet reusing the question-list editor from
  `edit-interview-baseline-sheet.tsx` (extracted into a shared component
  if it is not one already), plus a probe-mode select and an "include the
  job's own questions" switch; archive and unarchive.
- **Job details** — `edit-job-details-sheet.tsx` gains a "Default
  interview template" select.
- **Round start** — "Mark as scheduled" and "Another round" open a small
  picker: every active template, the job's default preselected, plus "No
  template". **When no active templates exist the picker does not
  appear**, and both buttons stay a single click, exactly as today.
- **Kit header** — shows the template name next to the round, e.g.
  "Round 2 · RH screen".

## Migration

One additive migration: create `interview_templates` with its partial
unique index, add `jobs.default_interview_template_id`, add the three
`interview_kits` columns. Everything is nullable or defaulted, so there
is no backfill and the downgrade simply drops what was added. Verified
upgrade → downgrade → upgrade against a scratch Postgres, as in phase 1,
since the suite builds its schema with `create_all`.

## Testing

1. `fixed_questions` and `wants_probes` across every row of the table
   above, including no template.
2. Namespacing: a template question and a job baseline question sharing
   an id both survive, with distinct ids, and a sheet answer keyed to
   each stays with the right one.
3. Scheduling with an explicit template, with the job's default, with
   explicit `null`, and with an archived template (422).
4. `interview_template_id` sent with a non-scheduled stage → 422.
5. Reopening with the same template copies forward; with a different
   template seeds fresh from the new one and does not carry the previous
   round's questions.
6. Editing a template after a kit was created does not change that kit,
   and regenerating the kit still uses its snapshot.
7. `probe_mode: none` makes zero LLM calls and still ends `ready`.
8. Template CRUD: duplicate question ids, name uniqueness among active
   templates, archive frees the name, viewers are refused.
9. Frontend: the picker preselects the job's default, offers "No
   template", and does not appear when no active templates exist; the
   Settings tab creates, edits and archives.
10. Migration round-trip against real Postgres.

## Risks

- **The snapshot is deliberately deaf to template edits.** An admin
  fixing a typo in the RH template will not see it in a round already
  under way, and regenerating that kit will not pick it up either. That
  is the constraint that protects closed rounds, applied uniformly; the
  kit header naming its template makes the source visible.
- **Reopening changes behaviour when the template changes.** Same
  template keeps phase 1's copy-forward; a different one seeds fresh,
  which means questions appended by hand in the previous round do not
  carry into a round of a different kind.
- **Scheduling gains a click once templates exist.** Mitigated by the
  preselected default and by the picker not appearing at all until the
  first template is created.

## Where this is going

- **Phase 3 — tracks.** A round holds several kits, each with its own
  template; `template_id` already sits on the kit row, so a track is a
  kit with a template rather than a new concept.
- **Phase 4 — profile probes.** `probe_mode` gains `profile`: probes
  drawn from career history and enrichment instead of the score
  breakdown, which is what RH templates should switch to.
