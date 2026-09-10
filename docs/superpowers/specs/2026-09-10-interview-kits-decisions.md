# Interview kits — decisions and follow-ups

Date: 2026-09-10
Status: record (feature merged in #19)
Design: `2026-09-10-interview-kits-design.md`
Plan: `../plans/2026-09-10-interview-kits.md`

The design says what was intended and the plan says how it was built. This
records what changed *during* the build: decisions taken against the plan, and
the work knowingly left undone. Both were held in a scratch execution ledger
that does not survive; the parts worth keeping are here.

## Defects in the plan, and what was done instead

Five. Each was caught by review or by an implementer refusing to write
something that could not run — none by the plan's own self-review.

**`require_role(Role.RECRUITER)` would have locked the admin account out.**
`require_role` is a membership test (`user.role not in allowed`,
`api/deps.py:86`), so a RECRUITER-only gate 403s an ADMIN — and the seed
account is an admin. It was redundant as well: `api/deps.py:108-121` registers
an app-wide default-deny guard that refuses viewers every mutating method
unless the route is in `VIEWER_ALLOWED_ROUTES`, and `api/permissions.py` says
in as many words that it exists so "a router that does not exist yet is
covered the day it is added". The interview endpoints therefore carry **no
route-local role gate**. A test asserts a viewer gets 403 on generate and 200
on read.

**`Depends(get_llm)` on `patch_application` would have broken the kanban.**
FastAPI resolves dependencies eagerly, so with no LLM provider configured
*every* PATCH to an application — including 404s and stage moves that never
touch a model — would have returned 503. `api/jobs.py`'s `get_llm_or_none`
already existed for exactly this, and its docstring documents the trap. The
pre-existing `test_patch_404_when_missing` caught it.

**Entering `SCHEDULED` must preserve `questions`.** The plan reset them to
`[]`, which would have destroyed recorded answers for a candidate moved back
to Scheduled after an interview.

**Three transcription-level errors:** `CriteriaItem(weight=20)` cannot
validate (`weight` is `ge=0.0, le=1.0`); `ApplicationUpdate.stage` has no
`"invited"` literal, so tests cannot PATCH through it; and
`from tests.api.conftest import ...` fails because `tests` is not an
importable package — `create_scored_app` is a fixture instead.

**SSE panel updates were specified and never implemented.** The design says
the panel updates over SSE "exactly as stage changes already do", and no task
built it. Caught only during end-to-end testing, when the panel sat on
"Generating questions…" indefinitely. Worth noting *how* the first fix failed:
adding the handler was not enough, because the backend emits a **named** event
(`api/events.py:29` → `event: interview_kit`) and `EventSource` never routes
named events to `message` listeners. A test that called the handler directly
passed while the browser path stayed dead.

## Two constraints reversed mid-build

**The ruff baseline moved 233 → 244.** An implementer added `# noqa: B008`
comments to hold the old number and flagged them as a style outlier. It was
right: this codebase carries 91 unsuppressed `B008` warnings on `Depends(...)`
defaults, and a new FastAPI router legitimately adds more. Silencing warnings
in one file to hit a number is worse than the number moving.

**The e2e spec was rewritten to seed its own fixture.** It originally hunted
for a candidate parked at `scheduled` and skipped when none existed — and
because the suite never leaves one in that state, it would have skipped on
essentially every run while permanently mutating a candidate it did not own.

## Frontend conventions worth not rediscovering

Three defects recurred often enough during this build to be worth stating.

- **Per-row controls need accessible names keyed on row index, never on
  mutable text.** Two blank rows otherwise produce two identical labels,
  breaking screen readers and tests alike. Hit three times.
- **Generated row ids must be collision-proof.** `Date.now()` alone collides
  on two clicks in the same millisecond, after which editing one row edits
  both.
- **The app is permanently dark-themed.** `darkMode: "class"` is configured
  but no `.dark` class is ever applied, so `dark:` variants never match and a
  light surface without explicit dark text is invisible. A previous banner
  shipped at roughly 1.05:1 contrast this way.

## Follow-ups, in the order worth doing

1. **`JobRead.interview_baseline` is `list[dict] | None`** where `criteria`
   beside it is properly typed. Should be `list[BaselineQuestion] | None`.
2. **`tests/api/test_chat_api.py` still carries its own `_create_scored_app`.**
   Only `test_chat_search_tool.py` moved to the shared fixture — a
   half-finished dedupe.
3. **No test covers clearing a baseline** with `PUT {"questions": []}`.
   Clearing is a real action and `[]` is deliberately distinct from the `None`
   "never set" default.
4. **Replace `window.confirm`** on the unanswered-submit path with a real
   dialog. It is unstyled against the rest of the app and untestable, which is
   why that path has no test.
5. **The kit panel lacks its sibling's border and padding.** Two panels on one
   page with two treatments (`enrichment-section.tsx` uses
   `space-y-4 rounded border p-4`).
6. Smaller: no test submits from `OFFER`/`HIRED` to prove the advance-once
   guard holds there; `generate`/`submit` call `api()` without a generic so a
   future caller reading the returned kit gets `unknown`; the Baseline header
   button has no count badge where Criteria does.

## The open question

Whether the generated probes are sharper than what a recruiter would write
unaided. The design names this as the risk tests cannot answer, and it remains
unanswered: one kit was read against a real candidate during end-to-end
testing and its questions were criterion-tied and specific rather than
generic. That is one data point. It needs a recruiter reading real output on
real candidates before the feature is called done.
