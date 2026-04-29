# Recruiter Agent — Phase 1 Design

**Date:** 2026-04-29
**Status:** Draft — pending user review
**Scope:** Phase 1 MVP only (single-user, localhost). Phases 2–4 noted for context but out of scope.

---

## Purpose

Build a recruiter assistant that helps a recruiter source candidates from URLs and resumes, score them against a job description plus custom criteria, and — after human validation — send personalized outreach with an interview invitation. The recruiter remains the decision-maker; the agent does the prep, scoring, drafting, and sending.

## Non-Goals (Phase 1)

- Authentication, multi-user, SSO, RBAC — deferred to Phase 4.
- LinkedIn scraping infrastructure (proxies, headless browsers) — deferred to Phase 2. Phase 1 supports a "paste content" fallback for LinkedIn URLs.
- Bulk candidate upload, candidate pool reusable across jobs — deferred to Phase 2.
- LinkedIn DM, Calendly-style booking links — deferred to Phase 3.
- Compliance audit logs, full audit trail UI — deferred to Phase 4 (lightweight event log present in Phase 1 to lay groundwork).
- OCR for scanned resumes — deferred.
- Background queue (Celery/RQ) — Phase 1 uses FastAPI `BackgroundTasks`.
- E2E browser testing — deferred until UI is stable.

## Phasing (context, out of scope here)

- **Phase 2:** GitHub API + LinkedIn scraping (proxy infra, third-party services), bulk resume upload, candidate pool.
- **Phase 3:** LinkedIn DM, Calendly-style booking, calendar reply tracking.
- **Phase 4:** Enterprise — Google/Microsoft SSO, RBAC, full audit logs, compliance.

## User Workflow (Phase 1)

1. Recruiter creates a `Job` with a JD and optional custom weighted criteria.
2. For each candidate, recruiter pastes a URL or uploads a resume (PDF / DOCX / pasted text). LinkedIn URLs are stored as links; recruiter pastes profile content separately.
3. Agent extracts structured candidate data and scores the candidate against the JD + criteria. Result appears on a kanban board for that job.
4. Recruiter reviews score breakdown and rationale; uses a per-candidate chat panel for nuanced questions; clicks **Validate**.
5. Recruiter clicks **Notify & invite**, picks a notification channel (Gmail+GCal or SMTP+ICS), enters 2–3 free interview slots, reviews the LLM-drafted email, edits as needed, and sends.
6. Application advances to `invited`; transitions to `scheduled` when the calendar invite is accepted (Gmail+GCal path detects this in Phase 2; Phase 1 stays at `invited` after send).

## Decisions Locked

| Area | Decision |
|---|---|
| Sources | Any URL (smart routing: GitHub API / LinkedIn store-link / generic fetch+extract) + resume upload (PDF, DOCX, plain text paste) |
| Form factor | Web app — FastAPI backend + React frontend |
| LLM | Pluggable client with two backends: Anthropic Claude API and OpenAI-compatible local endpoint (Ollama/vLLM serving GPT-OSS 120B). Per-task provider override. |
| Scoring | LLM-based, against JD + custom weighted criteria |
| Job model | Multiple jobs, each with kanban pipeline (extracting → scored → validated → invited → scheduled \| rejected). `sourced` stage exists in the enum but is unused in Phase 1; reserved for Phase 2 when bulk uploads may queue candidates without immediate processing. |
| Candidate input | Manual, one-at-a-time, assigned to a job |
| Notifications | Two backends behind one interface: Google OAuth (Gmail + Calendar) **or** SMTP send + ICS attachment |
| Auth | None — localhost only |
| DB | PostgreSQL (SQLAlchemy 2.0 + Alembic) |
| Async | FastAPI `BackgroundTasks`; SSE for live UI updates |
| Resume storage | Local filesystem; path stored in DB |
| Secret storage | Encrypted at rest in `Settings` row using a key from env (`SETTINGS_KEY`, AES-GCM/Fernet) |
| Approach | Pipeline (deterministic) for the bulk path + agentic chat panel on candidate detail |

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Browser (React + Vite + TypeScript)            │
│   Pages: Jobs list, Job kanban, Candidate       │
│   detail (with chat panel), Settings            │
└──────────────────┬──────────────────────────────┘
                   │ REST + SSE
┌──────────────────▼──────────────────────────────┐
│  FastAPI backend (Python 3.11+)                 │
│   api/  pipeline/  agent/  notifications/       │
│   llm/  models/  schemas/                       │
└──────┬──────────────┬──────────────┬────────────┘
       │              │              │
┌──────▼──────┐ ┌─────▼─────┐ ┌──────▼─────────┐
│ PostgreSQL  │ │  LLMs     │ │ Google APIs    │
│ + Alembic   │ │ Claude /  │ │ Gmail+Calendar │
│             │ │ Local 120B│ │ (OAuth)        │
└─────────────┘ └───────────┘ └────────────────┘
                                  + SMTP fallback
```

### Backend modules

- `api/` — FastAPI routes: `jobs.py`, `candidates.py`, `applications.py`, `chat.py`, `notifications.py`, `settings.py`, `events.py` (SSE).
- `pipeline/` — deterministic processing.
  - `router.py` — dispatches input to right fetcher/parser based on URL/file type.
  - `fetchers/` — `github.py`, `webpage.py`, `linkedin_stub.py`.
  - `parsers/` — `pdf.py` (PyMuPDF), `docx.py` (python-docx), `text.py`.
  - `extractor.py` — LLM call: raw text → structured candidate fields + `raw_extracted` JSON.
  - `scorer.py` — LLM call: candidate + JD + criteria → score, breakdown, rationale.
  - `email_drafter.py` — LLM call: candidate + JD + slots → draft email body/subject.
- `agent/` — chat panel.
  - `tools.py` — read tools (`get_candidate`, `get_application`, `get_score_breakdown`, `get_job`, `list_other_applications_for_candidate`); write tool (`save_note`).
  - `chat.py` — conversation handler, system prompt grounded in current candidate × job, JD + criteria + extracted candidate data preloaded and prompt-cached.
- `notifications/` — `google_oauth.py`, `gmail.py`, `gcal.py`, `smtp.py`, `ics.py`. Single `Notifier` interface.
- `llm/` — `client.py` (interface: `chat`, `chat_structured`), `anthropic.py`, `openai_compat.py`.
- `models/` — SQLAlchemy 2.0 declarative models.
- `schemas/` — Pydantic schemas (request/response, internal DTOs).

### Frontend modules

- `pages/` — `JobsList`, `JobDetail` (kanban), `CandidateDetail` (with chat panel), `Settings`.
- `components/` — `KanbanBoard`, `CandidateCard`, `ScoreBreakdown`, `ChatPanel`, `AddCandidateModal`, `NotifyModal`.
- `lib/` — API client (typed), SSE hook, types generated from OpenAPI.
- State: TanStack Query for server state; component-local state otherwise.

## Data Model

```
Job
├─ id, title, description (JD text)
├─ criteria: JSON [{name, weight (0-1), description}]
├─ status: enum [open, closed]
└─ created_at, updated_at

Candidate
├─ id
├─ Identity: full_name, email, phone, location, headline
├─ Profile: summary, skills (JSON[]), experience (JSON[]), education (JSON[]), links (JSON[])
├─ Source: source_type (url|resume|paste), source_url, resume_path
├─ raw_extracted (JSON) — full LLM extraction output, for debugging / re-derivation
└─ created_at, updated_at

Application
├─ id, job_id, candidate_id  (unique on job_id+candidate_id)
├─ Score: score (0-100), score_breakdown (JSON per-criterion), score_rationale (text)
├─ Stage: enum [sourced, extracting, scored, validated, invited, scheduled, rejected]
├─ Stage timestamps: validated_at, invited_at, scheduled_at, rejected_at
├─ notes (text)
└─ created_at, updated_at

Notification
├─ id, application_id
├─ channel: enum [email, calendar]
├─ provider: enum [gmail, smtp]
├─ subject, body
├─ status: enum [draft, sent, failed]
├─ external_id  (Gmail message id, GCal event id)
└─ sent_at, created_at, updated_at

Settings  (single row)
├─ LLM: default_provider, anthropic_api_key (encrypted), local_llm_url, model_overrides (JSON: {extract: 'local', score: 'claude', email: 'claude', chat: 'claude'})
├─ Notifier: google_oauth_tokens (encrypted), smtp config (encrypted)
├─ Misc: resume_storage_path, recruiter_name, recruiter_email, monthly_llm_spend_cap_usd

EventLog  (lightweight audit foundation)
├─ id, application_id (nullable), event_type, actor (always 'recruiter' in Phase 1), payload (JSON), created_at
```

Keeping `Candidate` separate from `Application` means the Phase 2 candidate pool is a model-only change (no schema migration beyond a new join table).

## Data Flows

### Flow A — Add candidate to a job

1. User on Job page → "Add candidate" → modal (URL tab or Resume tab).
2. `POST /api/jobs/{job_id}/candidates` body: `{url}` or multipart `{file}`.
3. Backend creates `Candidate(stage=extracting)` and `Application(stage=extracting)`; returns 202 with `application_id`.
4. `BackgroundTask`: router → fetcher/parser → `extractor` (LLM) → fills Candidate fields → `scorer` (LLM, JD prompt-cached) → fills Application score, breakdown, rationale → stage `scored`.
5. SSE pushes events `extracting → scored` with payloads; frontend kanban moves the card.

### Flow B — LinkedIn URL

- Stored as `source_url`. Card shows "Paste profile content" prompt.
- User pastes copied profile text into a textarea; that goes through extractor → scorer like any other input.

### Flow C — Validate → Notify → Invite

1. User reviews Candidate detail (score breakdown, rationale, structured profile).
2. Click **Validate** → `Application.stage = validated`.
3. Click **Notify & invite** → modal:
   - Channel: `gmail` or `smtp`.
   - Slot picker: 2–3 free time slots (Phase 1: typed manually; Phase 3: pulled from Calendar availability).
   - "Draft email" → LLM drafts subject + body referencing JD and candidate specifics.
   - Editable preview.
4. **Send**:
   - Gmail path: send email + create GCal event with candidate as attendee → store event id.
   - SMTP path: build ICS file with proposed slots, attach, send via SMTP.
   - `Notification` row created; `Application.stage = invited`.

### Flow D — Per-candidate chat panel

- Right-side panel, persistent conversation per Application.
- Claude with tools (read: `get_candidate`, `get_application`, `get_score_breakdown`, `get_job`, `list_other_applications_for_candidate`; write: `save_note`).
- System prompt: "You are a recruiting assistant helping evaluate candidate X for role Y." JD + criteria + extracted candidate data preloaded into the initial system message and prompt-cached.

## Error Handling

- **LLM failures** — retry with exponential backoff (3 attempts: 1s, 4s, 15s). On final failure, hold stage and surface a "Retry" affordance in the UI. UI offers one-click switch to the other provider for that task.
- **Web fetch failures** — surface error and offer the manual paste fallback (same path used for LinkedIn URLs). Robots.txt is checked for non-API generic fetches; if disallowed, refuse and offer manual paste.
- **Resume parsing failures** — encrypted PDFs, scanned PDFs without a text layer, or oddly encoded DOCX files surface an error with a "paste text" option.
- **Google OAuth** — refresh expired tokens silently. If refresh fails or scopes change, redirect to re-consent. Send failures (rate limit, attachment size) backoff then surface.
- **Validation guards** — Validate is enabled only after `scored`; Notify only after `validated` AND `candidate.email` exists. Notify modal collects email if missing.
- **Concurrent edits** — optimistic concurrency on `Application` via `updated_at`; stale writes return 409 and the UI reloads.
- **Cost guardrails** — optional `monthly_llm_spend_cap_usd` in Settings (Claude API only; local is free). Banner when approaching, hard block when exceeded until next month or cap raised.
- **API errors** — RFC 7807 Problem Details JSON across the API.

## Testing Strategy

- **Unit tests** (fast, mocked LLM):
  - `pipeline/fetchers/`: mock httpx for webpage; cassettes for GitHub API.
  - `pipeline/parsers/`: real PDFs/DOCX in `tests/fixtures/resumes/`; assert extracted text contains key strings.
  - `extractor`, `scorer`, `email_drafter`: mock LLM client; assert prompts contain right context; assert structured outputs are parsed.
  - `notifications/`: mock Gmail/SMTP; assert payloads.
- **LLM integration tests** (real LLM, opt-in):
  - `pytest-recording` (VCR) — first run hits real API, subsequent runs replay cassette.
  - Use Claude Haiku for cassette regeneration to keep cost low.
  - Assertions on shape and sanity (score in `[0, 100]`, required fields present), not exact wording.
- **API tests** — FastAPI `TestClient` against a real Postgres test DB (testcontainers); LLM client overridden to a fake. Cover full add → score → validate → notify and chat panel turn.
- **Frontend** — Vitest + React Testing Library; MSW for API mocking. No E2E in Phase 1.
- **Manual smoke checklist** — GitHub URL happy path, PDF happy path, LinkedIn paste flow, Gmail send (real account), SMTP+ICS send (real account), chat panel with both LLM providers, settings provider switch mid-session.
- **Out of scope** — load/perf testing, security/pen testing.

## Open Questions

- None blocking. The following are flagged for future phases:
  - Which Google API scopes exactly? Will be finalized during implementation; minimum scopes for `gmail.send` and `calendar.events`.
  - Local LLM tool-calling reliability (GPT-OSS 120B): if poor, the chat panel may need to be Claude-only even when extraction/scoring uses local. Implementation will confirm.
