# Plan B — Manual Smoke Test Checklist

Run before declaring Plan B done.

## Setup

```bash
# Backend
docker compose up -d postgres
.venv/bin/alembic upgrade head
.venv/bin/uvicorn recruiter.main:app --port 8000

# Frontend (separate terminal)
cd recruiter-frontend
npm run dev
```

Open `http://localhost:5173`.

## Theme

- [ ] Theme toggle (header dropdown) flips light/dark.
- [ ] Refresh — chosen theme persists.
- [ ] Pick "System" — toggle reflects OS preference.

## Jobs

- [ ] `/jobs` shows empty state with "Create your first job" CTA.
- [ ] Click CTA → `/jobs/new`.
- [ ] Submit empty form → "Title is required" error inline.
- [ ] Add a criterion via "Add criterion", then remove it via the trash icon.
- [ ] Fill title + description + 1 criterion, submit → redirects to `/jobs/{id}`.
- [ ] Back to `/jobs` shows the new job in the list.

## LLM Settings

- [ ] `/settings` → LLM tab shows "Anthropic" provider, no key set.
- [ ] Enter your real `sk-ant-…` key, save → toast "Settings saved", masked indicator updates.
- [ ] Switch provider to "Local", enter `http://localhost:11434/v1`, save.
- [ ] Switch back to Anthropic before continuing.

## Add candidate (URL paste)

- [ ] On `/jobs/{id}`, click "Add candidate" → slide-over opens with URL/Upload/Paste tabs.
- [ ] Paste tab → `Alice Doe — senior backend engineer with Rust and Postgres` → submit.
- [ ] Toast "Candidate added — extracting…" appears, slide-over closes.
- [ ] Card appears in **Extracting** column briefly, then transitions to **Scored** via SSE.
- [ ] Score badge appears on the card with color reflecting score.

## Application detail + actions

- [ ] Click the card → `/applications/{id}` shows score breakdown with per-criterion bars + rationale.
- [ ] Action bar shows "Validate" + "Reject".
- [ ] Click Validate → stage badge becomes "validated"; bar shows "Unvalidate" + "Notify & invite" + "Reject".
- [ ] Click "Notify & invite" → toast "Notify wizard ships in Plan C".
- [ ] Click Unvalidate → stage returns to "scored".
- [ ] Re-validate → stage "validated".
- [ ] Click Reject → dialog opens, type "test reason", confirm → stage "rejected".
- [ ] Back to `/jobs/{id}` → toggle "Show rejected" reveals the candidate in the Rejected column.

## Drag-drop (desktop, viewport ≥ 1024px)

- [ ] Add a second candidate via paste so it lands in Scored.
- [ ] Drag the card from Scored → Validated → it patches successfully.
- [ ] Drag from Validated → Scored (unvalidate) → succeeds.
- [ ] Try dragging from Validated → Invited → toast "Cannot move from validated to invited" (UI guard).
- [ ] Cards in Extracting column are not draggable (no grab cursor).

## Resume upload

- [ ] Open Add candidate, Upload tab, select a `.pdf` resume → submit.
- [ ] Card appears in Extracting → Scored.
- [ ] Try uploading a `.txt` file → 415 toast.

## LinkedIn URL flow

- [ ] Add via URL, paste `https://www.linkedin.com/in/alice/` → 202.
- [ ] Card stays in Extracting (no LLM call).
- [ ] *(Manual paste flow not yet UI-surfaced in Plan B; backend `POST /api/applications/{id}/paste` works via curl.)*

## Mobile (DevTools 375px)

- [ ] Kanban becomes single-column (no horizontal scroll).
- [ ] Drag-drop is disabled.
- [ ] Action buttons remain visible and functional.
- [ ] Theme toggle still works.

## Failure surface

- [ ] Stop the backend mid-session → kanban stays as last cached state, mutations toast "API connection error" or similar.
- [ ] Restart backend → SSE reconnects (silent).


## Plan C — SMTP smoke

Requires MailHog running on localhost:1025 (SMTP) and 8025 (UI):

```bash
docker run -d --rm --name mailhog -p 1025:1025 -p 8025:8025 mailhog/mailhog
```

- [ ] In Settings → Notifications, save SMTP config: host=localhost, port=1025, user=any, password=any, from=me@example.com.
- [ ] Add a candidate with paste content `Alice Doe alice@example.com - Rust expert` → wait for Scored.
- [ ] Click candidate → Validate → "Notify & invite".
- [ ] Wizard step 1 (Channel): SMTP option enabled. Pick it, Next.
- [ ] Step 2 (Slots): Add 2 slots, Next.
- [ ] Step 3 (Draft): AI auto-drafts subject + body. Edit subject. Next.
- [ ] Step 4 (Confirm): Review, click Send. Toast "Invitation sent".
- [ ] Card moves to Invited column on the kanban.
- [ ] Open MailHog UI (http://localhost:8025). The email is present, has `text/calendar` attachment.
- [ ] Open the .ics in any calendar app — attendee should be `alice@example.com`, organizer should be your `from_email`.
- [ ] Try Notify on a candidate without an email → Notify button is hidden (canNotify guard).
- [ ] Try Notify on a candidate with no SMTP configured → 503 toast "SMTP config not set in settings".

## Plan D — Chat panel

Prereqs: backend + frontend running, an application in stage `scored`, an LLM
provider configured (`/api/settings`).

- [ ] Open `/applications/<scored-app-id>` → chat panel mounted on the right, history empty.
- [ ] Type "summarize her async-Rust experience" + press Enter.
  - [ ] Input disables while streaming, "Thinking…" indicator appears.
  - [ ] Assistant text appears (no tool call card for a simple read query).
- [ ] Type "validate her with note 'strong RustConf signal'".
  - [ ] A `validate_application` tool card renders.
  - [ ] Application stage on the left side / kanban moves to Validated.
  - [ ] An "Undo" button is visible on the tool card.
  - [ ] Click Undo → kanban reverts to Scored within ~1s.
- [ ] Refresh the page → entire conversation reloads from the DB in order.
- [ ] Kill the backend mid-turn → red error banner appears in the panel.
- [ ] Restart backend → next user message succeeds.
