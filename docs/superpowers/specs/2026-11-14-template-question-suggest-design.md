# Suggest questions for an interview template

Date: 2026-11-14
Status: draft (design, awaiting approval)
Builds on: `2026-09-21-interview-templates-design.md`

## Why

HR questions (motivation, notice period, career moves) fit almost any job, so
one HR template serves the whole organisation. Technical interviews do not: a
DevOps, a backend and a data-science round ask about different things. The
answer today is one technical template per speciality, but the admin writes
every question of every one by hand, and the template editor offers no help.

This adds a **Suggest questions** button to the template editor that drafts a
starting question set for the speciality, which the admin keeps, edits or
deletes before saving.

## Goals

- Draft 5–8 questions for a template from its name, description and kind.
- Optionally ground them in an existing job's description, chosen in the
  editor, for when a new speciality template is created because such a job
  just opened.
- Work for every kind; most useful for Technical.

## Non-goals

- No change to how kits are generated per candidate. Template questions
  remain fixed questions; generated probes are untouched.
- No per-job template restrictions. Templates stay organisation-wide; the
  chosen job only feeds the suggestion and is not stored on the template.
- No suggestion in the job's baseline sheet or anywhere else.

## Anti-goals

- Suggestions silently replacing questions the admin already wrote.
- Anything persisted before the admin clicks Save.
- Generic filler ("Tell me about yourself") on a Technical template.

## Approaches

1. **One structured LLM call behind a new endpoint, copying Suggest from JD**
   for criteria (`criteria_suggester.py`, `POST /api/jobs/criteria/suggest`).
   **Picked:** one round trip, structured output, an established pattern in
   the codebase with the same error handling.
2. Calling the per-candidate *Draft with AI* several times. Rejected: it needs
   an application, and costs one slow call per question.
3. Going through the chat agent. Rejected: the agent is bound to one
   application and returns prose, not rows.

What the model reads, decided with the user: **the template (name,
description, kind) plus, optionally, an existing job** picked in the editor.

## Design

### Backend

- `src/recruiter/pipeline/template_question_suggester.py`:
  `suggest_template_questions(*, name, description, kind, job_title,
  job_description, existing, llm) -> list[SuggestedQuestion]`.
  - One `chat_structured` call returning `{questions: [{text, criterion}]}`;
    `criterion` names the skill or theme the question tests (≤ 200 chars).
  - System prompt by kind:
    - **technical**: questions probing the speciality's core skills, asking
      for concrete stories and trade-offs rather than "do you know X";
      no generic or HR questions.
    - **hr**: motivation, expectations, career path and team fit; no
      technical-stack questions.
    - **custom**: follow the description.
  - The template's name and description and the job's title and description
    are pasted text: fenced and cleaned with the helpers already used in
    `interview_kit_generator.py` (`_clean`, `_fenced`), and the job
    description capped (same 700-character budget as `_ROLE_RULE`'s block).
  - `existing` (the questions already in the editor, text only) goes in as
    "do NOT repeat these", so a second click adds new ones.
  - Fewer than 5 or more than 8: one retry with the count stated, as the
    criteria suggester does; still out of range → keep the first 8, or
    error if none.
- Endpoint `POST /api/interview-templates/suggest-questions` on the existing
  templates router (admins and recruiters; viewers refused by the existing
  read-only guard, since it is a POST not on the allow list).
  - Request: `name` (1–128), `description` (≤ 2000, optional), `kind`
    (`technical | hr | custom`), `job_id` (optional), `existing` (list of
    strings, each ≤ 2000, at most 50).
  - `job_id` unknown → 404. LLM failure → 502 "Question suggestion failed",
    logged, like criteria suggestion.
  - Response: `{questions: [{text, criterion}]}`. Nothing is written.

### Frontend (`interview-template-sheet.tsx`)

- Next to **Add question**: a **Suggest questions** button (sparkles icon, as
  on Suggest from JD), disabled until the template has a name, and while a
  request is in flight ("Suggesting…").
- Above it, an optional **Based on job** select listing jobs (open first),
  defaulting to "No job".
- On success the questions are **appended** below the existing rows as new
  editable rows with fresh ids, then the admin edits, deletes or saves as
  today. On failure, a toast: "Couldn't suggest questions — try again."
- Sketch:

  ```
  Questions
  Based on job: [ No job                 ▾ ]
  [ + Add question ]  [ ✦ Suggest questions ]
  Template question 1  [ Walk me through the last incident you led… ] [Remove]
  ```

## Testing

- Pipeline: prompt contents per kind, job block present only with a job,
  existing questions passed as do-not-repeat, count retry, fencing of pasted
  text (unit tests with a fake LLM, like the criteria suggester's).
- API: success shape, 404 on unknown job, 502 on LLM failure, viewer refused.
- Frontend: button disabled without a name, rows appended (not replaced),
  job id sent when picked, toast on failure.

## Left to the builder

- The exact prompt wording within the rules above.
- Whether the job list reuses `useJobs` as is or filters closed jobs.
- `max_tokens` (start from the 2048 the other suggesters use).
