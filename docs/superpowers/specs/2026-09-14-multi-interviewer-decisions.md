# Multiple interviewers — decisions and follow-ups

Date: 2026-09-14
Status: record
Design: `2026-09-14-multi-interviewer-design.md`
Plan: `../plans/2026-09-14-multi-interviewer.md`

## Deviations from the plan

### Defects in the plan, and what was done instead

**The plan's migration and its model disagreed on indexes.** The migration
created two indexes that `InterviewAssignment`'s model did not declare.
Review caught the drift; both indexes are now declared on
`InterviewAssignment.__table_args__` under the migration's own names, so
model and schema agree.

**`submit_sheet` had a last-submit race.** The plan's version re-read
assignments with no locking, so two simultaneous last submits on the same
application could both observe themselves as last and both close the round.
It was fixed by loading the application `with_for_update=True` in
`submit_sheet`, not merely documented as a known risk.

**The assign dialog had no empty states.** The plan's picker rendered a bare
empty list while the user directory was loading, and the chip row showed
nothing before assignments arrived — indistinguishable from "no users exist"
or "no one assigned." It now shows "Loading users…" and "No users match." in
the picker, and the chip row no longer renders a false "none" before
assignments have loaded.

**Three small transcription slips surfaced during the build.** Task 1's
Step 9 named a test file that does not exist; Testing Library's
`getByPlaceholderText` replaced the plan's `getByPlaceholder`, which is not a
real query; and Task 4's review had to be re-dispatched once after the first
reviewer died on an API timeout, unrelated to the plan's content but worth
keeping on the record.

### Scope that moved between tasks

**The viewer allow-list landed two tasks earlier than scheduled.** The plan
put `VIEWER_ALLOWED_ROUTES` entries in Task 6, but Task 4's own tests already
needed an assigned viewer to save a sheet, and Task 5's already needed one to
append a question. The two sheet routes were allow-listed in Task 4 and the
kit PATCH route in Task 5, which left Task 6 with only the permissions
docstring, the consolidated comment, and the exception test — so that test
passed on first write, with no red-first step.

**Task 8's frontend test files were merged into, not created.**
`use-interview-kit.test.tsx` and `sse.test.tsx` already existed, so the new
assertions were merged into them rather than written fresh: the pre-existing
"invalidates on submit" test was re-pointed at the sheet submit route, and a
`toHaveBeenCalledTimes(1)` became `(4)` to match the extra invalidation.

### Constraints reversed mid-build

**Question text stayed editable after a freeze.** The plan's Task 10 prose
made question text read-only once a round is frozen. The spec keeps question
renaming allowed after a freeze, because question ids — not their text — are
what stay stable, so the component keeps the question textarea editable for
recruiters after a freeze and disables only Remove.
`canWriteSheet`'s `sheets.length === 0` fallback was challenged in review for
the same reason and kept: it mirrors the server's own rule (no assignment
rows means auto-create; rows exist and the caller is unassigned means 404),
and now carries a comment and a guarding test to say so.

### Conventions worth not rediscovering

**New API test modules needed the repo's rate-limiter reset.** Tasks 4
through 6 added test modules that log in several users in a row, which trips
the login rate limiter unless the autouse `limiter.reset()` fixture is
present, the same fixture `test_viewer_matrix.py` already relies on.

**`EMPTY_SHEET` is frozen with `Object.freeze`.** It is a shared default
object; without freezing, an accidental mutation of it in one test would
silently leak into others. Freezing turns that mistake into a thrown error
instead.

**Recording a legacy answer for a regeneration test needed a different
route than before.** `test_re_entering_scheduled_preserves_answered_questions`
used to record its answer through the kit PATCH with a client-chosen id. Once
the legacy per-question `answer`/`rating` fields became read-only through
that route, the test could no longer set them that way, so it now writes the
legacy answer straight to storage and still asserts it survives regeneration
when the application re-enters `SCHEDULED`.

### Confirmed rather than changed

**No chat agent tool reads the interview kit.** The spec calls for the chat
agent to apply the same visibility filter as the rest of the feature, but a
grep of `src/recruiter/agent/` turns up no tool that reads the kit at all, so
there was nothing to filter and no task needed to touch the agent. Worth
re-checking if a kit-reading tool is ever added.

**Task 13's e2e spec passed on its first run, with no selector adjustments.**

## Follow-ups
1. Email or calendar-invite interviewers on assignment (out of scope by design).
2. Per-question interviewer tagging for split panels.
3. Multiple rounds with separate question sets.
4. The legacy per-question `answer`/`rating` fields and `submitted_at` can be
   dropped once no kit in any deployment carries them.
5. The e2e second-interviewer user is never deleted (no DELETE on users by
   design); clean it up with the E2E job cleanup.
6. The e2e second-interviewer flow relies on SMTP being configured locally,
   as the interview-kit spec's e2e already did.
