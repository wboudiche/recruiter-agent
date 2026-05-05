# Power-User Kanban (Plan H) — Design

**Author:** walid + claude
**Date:** 2026-05-05
**Status:** approved, ready for implementation plan

## Goal

Tighten the kanban + application-detail loop into a productivity-first surface for an active recruiter triaging dozens of candidates. Add five additive features — time-in-stage badges, density toggle, Cmd+K command palette, multi-select bulk actions, and a score-distribution strip — without rebranding or restructuring routes.

## Scope

### In scope (v1)

- **Time-in-stage badge** on every kanban card: subtle ageing indicator (`3d`, `5h`, `<1m`)
- **Density toggle** on the job page: comfortable (current) / compact (~2x more cards per column)
- **Cmd+K command palette**: fuzzy search across jobs, recent applications, settings, theme toggle, sign out
- **Magnifying-glass trigger** in the AppShell header so Cmd+K is discoverable without the keyboard
- **Multi-select on kanban**: shift-click toggles selection, floating bar offers Validate / Reject
- **Score-distribution strip**: 6px sparkline at the top of the Scored column showing where scores cluster

### Out of scope (deferred)

- Direct keyboard shortcuts (j/k navigate, v/r validate-reject, n new-candidate) — explicitly cut from this plan
- Voice input / agent suggestions / chat-first interface — see Plan H option C in design discussion
- Visual rebrand (typography hierarchy, gradients, illustrations) — see Plan H option A
- Visual regression tests (no Playwright snapshot infra)
- Inline editing on the application detail page
- Time-in-stage alerts / notifications

## Architecture

```
┌────────────────────────────────────┐
│ AppShell                           │
│ ├─ header: <SearchTrigger />       │  ← magnifying-glass icon
│ ├─ <CommandPalette />              │  ← always mounted, hidden until open
│ └─ Outlet (kanban / detail / etc.) │
└────────────────────────────────────┘

┌────────────────────────────────────┐
│ Job page (kanban)                  │
│ ├─ <KanbanDensityToggle />         │  ← header, persists to localStorage
│ ├─ <KanbanBoard>                   │
│ │   ├─ ScoreDistributionStrip      │  ← top of Scored column
│ │   ├─ CandidateCard (variant=...) │  ← compact / comfortable
│ │   │   ├─ TimeInStageBadge        │  ← bottom-right
│ │   │   └─ ring-2 (when selected)  │
│ │   └─ <BulkActionsBar />          │  ← floating, when ≥1 selected
│ └─ useKanbanSelection() hook       │  ← Set<number> state
└────────────────────────────────────┘
```

**No new API endpoints.** All five features render from data the frontend already has, or use the existing PATCH `/applications/{id}` for bulk actions.

## Components

### Backend

No backend changes. The score-distribution strip and time-in-stage derive from `ApplicationRead.score`, `created_at`, `validated_at`, etc.

### Frontend

```
recruiter-frontend/src/
├── components/
│   ├── command-palette/
│   │   ├── command-palette.tsx          # the modal
│   │   ├── command-palette-context.tsx  # open/close state shared by trigger
│   │   └── search-trigger.tsx           # magnifying-glass button in header
│   ├── kanban/
│   │   ├── kanban-density-toggle.tsx    # comfortable / compact segmented switch
│   │   ├── bulk-actions-bar.tsx         # floating bar, validate / reject
│   │   ├── score-distribution-strip.tsx # SVG sparkline at Scored column top
│   │   └── (modify) candidate-card.tsx  # density variant + time badge + selected ring
│   └── time-in-stage-badge.tsx          # 3d / 5h / <1m badge
├── hooks/
│   └── use-kanban-selection.ts          # Set<number> with toggle/clear
└── lib/
    └── time.ts                          # relativeTimeInStage helper
```

**Component contracts:**

```ts
// time-in-stage-badge.tsx
interface Props { application: ApplicationRead }
export function TimeInStageBadge({ application }: Props): JSX.Element;

// kanban-density-toggle.tsx
type Density = "comfortable" | "compact";
interface Props { value: Density; onChange: (d: Density) => void }
export function KanbanDensityToggle(props: Props): JSX.Element;

// candidate-card.tsx (extended)
interface Props {
  application: ApplicationRead;
  candidateName?: string;
  draggable?: boolean;
  density?: "comfortable" | "compact";   // new
  selected?: boolean;                    // new
  onShiftClick?: (id: number) => void;   // new
}

// command-palette.tsx
// Built on cmdk if added as a dep, otherwise inline Dialog + Input + filtered list.
// Keyboard:
//   Cmd+K / Ctrl+K — open/close
//   ↑/↓ — navigate items
//   Enter — execute
//   Esc — close

// use-kanban-selection.ts
interface SelectionApi {
  selected: Set<number>;
  toggle: (id: number) => void;
  clear: () => void;
  selectMany: (ids: number[]) => void;
}
export function useKanbanSelection(): SelectionApi;

// bulk-actions-bar.tsx
interface Props {
  selected: Set<number>;
  applications: ApplicationRead[];
  jobId: number;
  onClear: () => void;
}
export function BulkActionsBar(props: Props): JSX.Element | null;

// score-distribution-strip.tsx
interface Props { applications: ApplicationRead[] }  // already filtered to scored
export function ScoreDistributionStrip(props: Props): JSX.Element;
```

**Time helper:**

```ts
// lib/time.ts
export function relativeTimeInStage(app: ApplicationRead): {
  label: string;        // "3d", "5h", "<1m"
  ageingLevel: "fresh" | "warning" | "critical";  // <7d / 7-14d / >14d
};
```

## Data flow

**Time-in-stage:** pure derived render. `relativeTimeInStage(app)` picks the latest stage timestamp (`validated_at`/`invited_at`/`scheduled_at`/`rejected_at`) and computes elapsed time. Falls back to `created_at` for `extracting`/`scored`. Returns null fallback ("—") only if all timestamps are null. No state, no persistence.

**Density toggle:** `useState(() => readDensityFromStorage())` in the job-detail route; setter mirrors to localStorage on change. Wrapped in try/catch for SSR / private-browsing safety.

**Cmd+K command palette:**
- Open/close state in `command-palette-context.tsx` provided at the AppShell level
- Header `<SearchTrigger>` button + global `keydown(Cmd+K)` listener both call `setOpen(true)`
- Inside the palette: items grouped into sections — Jobs (from `useJobs()`), Recent applications (from localStorage `recent.applications`), Actions, Settings
- `recent.applications` pushed to on `ApplicationDetail` mount; capped at 10
- Selecting an item calls `navigate(...)` (react-router) and closes the palette
- No new API

**Multi-select:**
- `useKanbanSelection` hook owns `selected: Set<number>`, `toggle`, `clear`, `selectMany`
- `KanbanBoard` mounts the hook and threads `selected` + `onShiftClick` into each card
- `CandidateCard` shows `ring-2 ring-primary/50` when in selected set
- `BulkActionsBar` reads from same hook, shows when `selected.size >= 1`
- "Validate" / "Reject" runs `Promise.allSettled([...selected].map(id => api.patch(`/api/applications/${id}`, {stage})))`
- On all-success: clear selection + invalidate `queryKeys.jobApplications(jobId)`; toast `"Validated 5 applications"`
- On partial: per-failure toast, keep failed ids selected so user can retry

**Score distribution strip:**
- Renders inline SVG; reads from the `applications` array filtered to `stage === "scored"`
- For each card: a 1-2px tick at x = `(score / 100) * width`
- Tick color matches score band (red < 50, yellow 50-79, green ≥ 80)
- Hover (mouseover the tick): tooltip with candidate name + score
- Re-renders automatically via React when `applications` updates

## Error handling

- **Time-in-stage:** missing stage timestamp → fall back to `created_at`; if also null, render "—"
- **Density:** localStorage exception → fallback to "comfortable" silently
- **Cmd+K:** corrupted `recent.applications` JSON → ignore + treat as empty
- **Multi-select bulk actions:** per-card PATCH failure → toast each failure, retain failed ids in selection; bulk Reject ≥3 → confirmation modal listing first 3 names + total count
- **Score strip:** null score on a Scored row → render at left edge with `opacity-50`

## Testing

**Unit tests:**
- `tests/lib/time.test.ts` — `relativeTimeInStage` covers 5min / 3h / 3d / 14d / null
- `tests/hooks/use-kanban-selection.test.ts` — toggle adds/removes; clear empties; selectMany batches

**Component tests:**
- `time-in-stage-badge.test.tsx` — color thresholds at 7d / 14d
- `kanban-density-toggle.test.tsx` — click switches state; localStorage round-trip on mount + change
- `command-palette.test.tsx` — opens via Cmd+K KeyboardEvent; opens via header trigger; arrow-keys nav; Enter routes; Esc closes
- `bulk-actions-bar.test.tsx` — appears at ≥1; Validate dispatches N PATCH calls; partial failure toasts only the failed ones; selection persists for failed ids
- `score-distribution-strip.test.tsx` — N ticks for N scored apps; correct color band per tick

**Integration test:**
- Extend `kanban-board.test.tsx` — shift-click two cards → bar appears → click Validate → both transition; mock one PATCH to fail, verify only the failure stays selected

## Open questions

None blocking. The `cmdk` dep adds ~3KB gzipped and is the cleanest API; if we want to avoid a new dep, the same UX can be built on the existing shadcn `Dialog` + `Input` + a filtered list — slightly more code, same end result. Decide during implementation.
