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
