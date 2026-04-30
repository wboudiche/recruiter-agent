# Plan B/C/D — Frontend + Notifications + Chat Panel Unified Design

**Date:** 2026-04-30
**Status:** Draft — pending user review
**Scope:** Unified UX design across three implementation plans:
- **Plan B** — React frontend dashboard consuming the existing Plan A backend.
- **Plan C** — Notification backend (Gmail+GCal OAuth, SMTP+ICS) + frontend wiring.
- **Plan D** — Per-candidate chat panel: backend agent (Claude tool-use) + frontend UI.

Each plan ships working software on its own. Together they complete the Phase 1 MVP.

**Reference:** Phase 1 design at `docs/superpowers/specs/2026-04-29-recruiter-agent-design.md`. Backend lives at `src/recruiter/`.

---

## Purpose

Build the recruiter-facing dashboard for the recruiter agent. The recruiter manages multiple jobs, reviews scored candidates on a kanban, validates and rejects them, sends personalized outreach with interview slots, and converses with Claude about each candidate.

## Non-Goals (Phase 1)

- Multi-user, RBAC, SSO — Phase 4.
- LinkedIn DM, Calendly-style booking — Phase 3.
- Visual regression tests, accessibility audits, cross-browser matrix beyond Chrome/Firefox — defer.
- Bulk candidate import, candidate pool UI — Phase 2.
- Server-side rendering — single-user internal tool, SPA is sufficient.
- Job templates / criteria library — defer.

## Phase Decomposition

| Plan | Scope | End-state |
|---|---|---|
| **B** | Frontend SPA: jobs list, job kanban (with drag-drop on desktop, buttons everywhere), candidate detail with score breakdown, validate/unvalidate/reject flow, settings (LLM tab + Profile tab), theme toggle. **No** Notify, **no** Chat panel — those buttons return 501 placeholders. | A recruiter can paste candidates, watch them be scored, validate, and reject — fully visible in a UI. |
| **C** | Backend: Gmail+GCal OAuth, send endpoint, SMTP+ICS path, Notification model wiring. Frontend: NotifyWizard implementation + Settings → Notifications tab + Google connect button. | A validated candidate can be invited via real email + calendar invite. |
| **D** | Backend: `agent/` module with Claude tool-use, per-application chat endpoint, ChatMessage persistence model. Frontend: ChatPanel implementation. | Recruiter chats with Claude about a specific candidate; agent uses read tools and `save_note` write tool. |

## User Workflow (full Phase 1)

1. Recruiter opens the dashboard → lands on `/jobs` listing all open jobs.
2. Creates a new job at `/jobs/new` with title, JD, and weighted criteria.
3. On `/jobs/{id}`, opens the slide-over add-candidate panel; pastes a URL or uploads a resume.
4. Card appears in **Extracting** column; SSE pushes live transition to **Scored** with a 0–100 score badge.
5. Recruiter clicks the card → `/applications/{id}` shows score breakdown, full extracted profile, side-by-side chat panel.
6. Optionally chats with Claude ("does their experience match the JD?", "summarize their open-source work").
7. Drags or clicks **Validate** → card moves to **Validated** column. Recruiter can still **Unvalidate** before notifying.
8. Clicks **Notify & invite** → 4-step wizard: channel → slots → LLM-drafted email (editable) → confirm → send.
9. Card moves to **Invited**. SSE picks up the calendar accept (post-Phase-1) and moves it to **Scheduled**.
10. **Reject** path: open the reject dialog, optional reason, confirm → card moves to **Rejected** (hidden behind a "Show rejected" toggle).

## Decisions Locked

| Area | Decision |
|---|---|
| Repo strategy | Single git repo. Frontend in `recruiter-frontend/` directory as a sibling of `src/`. |
| Build | Vite 5 (instant HMR, zero-config TS). |
| Language | TypeScript (strict). |
| Routing | React Router v6 (data routers + nested routes). |
| Server state | TanStack Query v5. |
| Forms | React Hook Form + Zod resolvers. |
| Component library | shadcn/ui (Radix-based, copy-paste, owned). |
| Styling | Tailwind CSS with shadcn's CSS-variable theme tokens. |
| Theme | Light + dark with toggle, persisted in localStorage; respects `prefers-color-scheme` until explicit choice. |
| Responsive | Mobile + tablet + desktop, mobile-first breakpoints. Kanban becomes a stacked-accordion list view on mobile. |
| Drag-drop | `@dnd-kit/core` (accessible, mobile-aware). Hybrid: drag-drop on desktop, buttons everywhere. |
| Chat panel placement | Right-side persistent panel on candidate detail (collapsible). Mobile → full-screen modal. |
| Notify modal | 4-step wizard: Channel → Slots → Draft → Confirm. Mobile → full-screen sequence. |
| Settings layout | Tabs at top: LLM | Notifications | Profile. |
| Job creation | Dedicated page at `/jobs/new`. |
| Add candidate | Slide-over panel from the right with URL / Upload / Paste tabs. |
| Validation reversibility | Reversible until Notify is sent. After Notify: one-way. |
| Reject flow | Optional reason in modal; stored in `Application.notes` with `[REJECTED] ` prefix. |
| API types | Generated from `/openapi.json` via `openapi-typescript`. |
| Tests | Vitest + React Testing Library + MSW for API mocks. |
| API client | Hand-written typed fetch wrapper using generated types. |
| Auth in dev | None (localhost). Phase 4 adds SSO. |
| Backend stack additions | Plan C: `notifications/` package + `api/auth_google.py` + `api/notifications.py`. Plan D: `agent/` package + `api/chat.py` + `ChatMessage` model. |

## Architecture

```
┌────────────────────────────────────────────────────┐
│  Browser (React 18 + Vite + TypeScript)            │
│   Router:        React Router v6                   │
│   Server state:  TanStack Query                    │
│   Forms:         React Hook Form + Zod             │
│   UI:            shadcn/ui + Tailwind CSS          │
│   Drag-drop:     @dnd-kit/core                     │
│   Theme:         CSS variables, light + dark       │
└─────────────────────┬──────────────────────────────┘
                      │ REST + SSE (EventSource)
┌─────────────────────▼──────────────────────────────┐
│  FastAPI backend                                   │
│   Plan A (shipped):  jobs, candidates,             │
│                      applications, settings, SSE   │
│   Plan C (this work): /api/notifications,          │
│                      /api/auth/google              │
│   Plan D (this work): /api/applications/{id}/chat  │
└────────────────────────────────────────────────────┘
```

## Frontend Module Layout

```
recruiter-frontend/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.ts
├── components.json                # shadcn config
├── index.html                     # synchronous theme-detect script before React mounts
├── public/
└── src/
    ├── main.tsx
    ├── App.tsx                    # QueryClient + ThemeProvider + BrowserRouter
    ├── routes/
    │   ├── index.tsx              # → /jobs
    │   ├── jobs/
    │   │   ├── jobs-list.tsx
    │   │   ├── jobs-new.tsx
    │   │   └── job-detail.tsx
    │   ├── applications/
    │   │   └── application-detail.tsx
    │   └── settings.tsx
    ├── components/
    │   ├── kanban/
    │   │   ├── kanban-board.tsx
    │   │   ├── kanban-column.tsx
    │   │   ├── candidate-card.tsx
    │   │   ├── add-candidate-panel.tsx
    │   │   └── score-badge.tsx
    │   ├── candidate/
    │   │   ├── candidate-header.tsx
    │   │   ├── score-breakdown.tsx
    │   │   ├── chat-panel.tsx          # Plan D
    │   │   ├── action-bar.tsx
    │   │   └── reject-dialog.tsx
    │   ├── notify/                     # Plan C
    │   │   ├── notify-wizard.tsx
    │   │   ├── step-channel.tsx
    │   │   ├── step-slots.tsx
    │   │   ├── step-draft.tsx
    │   │   └── step-confirm.tsx
    │   ├── settings/
    │   │   ├── llm-tab.tsx
    │   │   ├── notifications-tab.tsx   # Plan C: Google connect button
    │   │   └── profile-tab.tsx
    │   ├── theme/
    │   │   └── theme-toggle.tsx
    │   └── ui/                          # shadcn-generated, owned
    ├── lib/
    │   ├── api.ts
    │   ├── api-types.ts                 # GENERATED
    │   ├── query-keys.ts
    │   ├── sse.ts
    │   └── format.ts
    ├── hooks/
    │   ├── use-jobs.ts
    │   ├── use-job.ts
    │   ├── use-job-applications.ts
    │   ├── use-application.ts
    │   ├── use-settings.ts
    │   └── use-chat.ts                  # Plan D
    └── styles/
        └── globals.css
```

## Backend Additions

```
src/recruiter/
├── api/
│   ├── auth_google.py             # NEW (Plan C)
│   ├── notifications.py           # NEW (Plan C)
│   └── chat.py                    # NEW (Plan D)
├── notifications/                 # NEW (Plan C)
│   ├── google_oauth.py
│   ├── gmail.py
│   ├── gcal.py
│   ├── smtp.py
│   ├── ics.py
│   └── notifier.py
├── agent/                         # NEW (Plan D)
│   ├── tools.py
│   └── chat.py
└── models/
    └── chat_message.py            # NEW (Plan D): per-application conversation history
```

Plan B also adds two small endpoints to the existing backend:
- `PATCH /api/applications/{id}` — accepts `{stage, notes?}` for the validate / unvalidate / reject transitions.
- `POST /api/applications/{id}/retry` — resets a failed-extraction application back to `extracting` stage and re-runs the orchestrator.

## Data Flows

### Flow A — App shell + initial load

1. `main.tsx` mounts `<App>` with `QueryClient`, `ThemeProvider`, `BrowserRouter`.
2. `App.tsx` opens an SSE connection to `/api/events` via `useSSE` (mounted globally).
3. `ThemeProvider` reads `localStorage["theme"]` (default: system preference); sets `<html class="dark">` or none. `theme-toggle` writes it back.
4. A synchronous `<script>` in `index.html` reads `localStorage` before React mounts, preventing flash-of-wrong-theme.

### Flow B — Jobs list → kanban

1. `/jobs` → `useJobs()` hits `GET /api/jobs`.
2. Click a job card → navigate to `/jobs/{id}`. `JobDetail` calls `useJob(id)` and `useJobApplications(jobId)` in parallel.
3. `KanbanBoard` groups applications by `stage`; renders 5 columns: Extracting, Scored, Validated, Invited, Scheduled. Rejected applications are hidden behind a "Show rejected" toggle.

### Flow C — SSE → cache invalidation

1. SSE event arrives: `{type: "stage", application_id, stage, score?}` or `{type: "error", application_id, phase, error}`.
2. `useSSE` calls `queryClient.invalidateQueries(["application", id])` and the per-job applications query.
3. TanStack Query refetches; kanban re-renders the moved card with a brief highlight animation.
4. Error events show a red banner on the card with a "Retry" button (calls `POST /api/applications/{id}/retry`).

### Flow D — Add candidate (slide-over)

1. Click "Add candidate" on a kanban → `<AddCandidatePanel>` slides in.
2. Three tabs: URL / Upload / Paste.
3. Submit → `POST /api/jobs/{id}/candidates` (URL/paste) or `POST .../upload` (file).
4. 202 Accepted → close panel; new card appears in `Extracting` column via SSE.
5. **LinkedIn URL special case:** server returns 202 but stage stays `extracting`. Card shows a "Paste profile content" affordance; click → opens a textarea; submit → `POST /api/applications/{id}/paste`.

### Flow E — Validate / Unvalidate / Reject (Plan B)

1. **Validate** (button on card or drag-drop to Validated) → `PATCH /api/applications/{id}` `{stage: "validated"}`.
2. **Unvalidate** (only on `validated` and only before Notify) → `PATCH .../{id}` `{stage: "scored"}`. Backend rejects with 409 if the application has already been notified.
3. **Reject** → opens `<RejectDialog>` with optional textarea; submit → `PATCH .../{id}` `{stage: "rejected", notes: "[REJECTED] " + reason}`.
4. All three optimistically update TanStack cache; revert on error toast.

### Flow F — Notify & invite wizard (Plan C)

1. Click "Notify" → `<NotifyWizard>` modal.
2. **Step 1 — Channel:** pick `gmail` or `smtp`. If `gmail` and not connected → "Connect Google" CTA.
3. **Step 2 — Slots:** 2-3 datetime ranges (datetime-local inputs).
4. **Step 3 — Draft:** `POST /api/applications/{id}/draft-email` returns `{subject, body}` from LLM. Editable.
5. **Step 4 — Confirm:** review, "Send" → `POST /api/applications/{id}/notify` with channel, slots, final subject+body.
6. 200 → close wizard. Stage becomes `invited`. Card shows email send timestamp.

### Flow G — Google OAuth (Plan C)

1. Settings → Notifications tab → "Connect Google".
2. Click → `GET /api/auth/google/start` returns `{auth_url, state}`. Browser navigates to Google.
3. Google redirects to `GET /api/auth/google/callback?code=...&state=...`. Backend exchanges code for tokens, encrypts via `SecretCipher`, writes to `Settings.google_oauth_tokens_enc`. Redirect to `/settings?google=connected`.
4. UI shows "Connected as `me@example.com`" with disconnect button.

### Flow H — Chat panel (Plan D)

1. Candidate detail page → right-side panel mounted in collapsed state on first visit.
2. Open → `useChat(applicationId)` loads history via `GET /api/applications/{id}/chat`.
3. User types → `POST /api/applications/{id}/chat` with `{message}`. Streaming response (SSE-style or NDJSON) is parsed chunk-by-chunk and rendered incrementally.
4. Backend agent (`agent/chat.py`) holds the conversation, calls Claude with read tools (`get_candidate`, `get_application`, `get_score_breakdown`, `get_job`, `list_other_applications_for_candidate`) and write tool `save_note`. Tool calls render as collapsed cards in the UI.
5. Conversation persisted in a new `ChatMessage` model linked to `Application`.

### Flow I — Settings

1. `/settings` → `useSettings()` loads from `GET /api/settings`. Tabs: LLM | Notifications | Profile.
2. Edit a field → form-level Zod validation. Submit → `PUT /api/settings` with only changed fields.
3. Secret fields (Anthropic key, SMTP password): write-only. UI shows `•••••• [Update]` if `has_anthropic_api_key === true`. Editing reveals an empty input.

## Error Handling

- **Network/API errors** — typed `ApiError` exposed via TanStack Query. Toasts (`Sonner`) for transient. Inline errors for 422. 404 renders "not found" page with back button.
- **SSE connection drops** — exponential backoff reconnect (1s, 4s, 15s, capped 30s). Banner after 5s of disconnect. Refetch all mounted queries on reconnect.
- **LLM pipeline failures** — `error` SSE event renders red banner on the card; "Retry" button calls `POST /api/applications/{id}/retry`.
- **Drag-drop validation** — `extracting` cards are not draggable; `Reject` drop requires confirmation; mobile = buttons only.
- **Form/wizard guards** — Next blocked without required fields. JD draft persisted to `localStorage` against accidental refresh.
- **Settings edge cases** — bad `RECRUITER_SETTINGS_KEY` surfaces as a setup banner with env-var instructions. Secrets never optimistically updated.
- **Concurrent edits** — TanStack Query refetch on focus. No optimistic concurrency tokens (deferred to Phase 4).
- **Mobile** — kanban → accordion list, chat panel → full-screen modal, notify wizard → full-screen sequence.
- **Theme** — system change while app is open updates if user hasn't explicitly chosen. Synchronous `<script>` prevents FOUC.
- **Audit prep** — every mutation sends an `X-Request-Id` UUID header.

## Testing Strategy

**Frontend unit + component tests** (Vitest + RTL + MSW)
- Hooks: mock API via MSW, assert TanStack Query loading/error/data.
- Components: `KanbanBoard`, `CandidateCard`, `ScoreBreakdown`, `NotifyWizard`, `RejectDialog`, `ChatPanel`.
- Drag-drop: `@dnd-kit/core` keyboard sensor; assert correct mutation fires on `Validated` drop.
- Forms: assert field-level errors, submit calls API.
- SSE: stub `EventSource`; assert query invalidations.
- Theme: toggle flips `<html class>`, persists, respects system.

**Backend tests for Plan C**
- `notifications/gmail.py`: mocked Gmail API; assert MIME and `messages().send()` payload.
- `notifications/smtp.py` + `ics.py`: ICS RFC 5545 round-trip via `icalendar`.
- `auth_google.py`: full state-token flow with mocked Google. (State token stored server-side in a short-TTL `oauth_states` table; Phase 1 has no session cookies.)
- `/api/notifications/draft-email` and `/notify`: API tests with FakeLLMClient + mocked notifier.

**Backend tests for Plan D**
- `agent/tools.py`: each tool tested in isolation.
- `agent/chat.py`: mock Claude tool-use loop with FakeLLMClient returning canned `tool_use` blocks.
- `/api/applications/{id}/chat`: streaming response shape, persistence.

**Manual smoke checklist** (per phase)
- Plan B: kanban CRUD + theme + mobile.
- Plan C: real Google OAuth → real email + calendar invite to your inbox; SMTP+ICS via MailHog.
- Plan D: chat with Claude about a candidate; verify tool calls and `save_note` persistence.

**Out of scope**
- Visual regression (Chromatic), load testing, formal a11y audit, cross-browser matrix beyond Chrome+Firefox.

## Open Questions

- None blocking. Items deferred for the implementation plans:
  - Exact Google OAuth scopes (`gmail.send` + `calendar.events` is the planned minimum).
  - LLM prompt for the email drafter — refined during Plan C implementation.
  - Chat tool-use schema details — Anthropic tool-use vs prompt-based JSON; will choose during Plan D based on whether the local 120B can handle Anthropic-style tool-use.
  - Whether to persist chat conversations across sessions or scope them per browser tab — leaning toward persistent (server-side `ChatMessage` rows per Application).
