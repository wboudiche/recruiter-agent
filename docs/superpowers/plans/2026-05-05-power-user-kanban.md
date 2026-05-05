# Power-User Kanban (Plan H) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add five additive frontend features — time-in-stage badge, density toggle, score distribution strip, multi-select bulk actions, and a Cmd+K command palette — to make the kanban + application detail loop faster for daily recruiter use.

**Architecture:** All five are pure-frontend additions on top of existing components. Time and selection state are derived/local. Cmd+K is global state in an AppShell-level context. No backend changes; multi-select reuses the existing PATCH /applications/{id} endpoint.

**Tech Stack:** React 18 + Vite + TanStack Query v5 + Tailwind + shadcn primitives + sonner toasts + react-router (frontend); no backend changes.

---

## Task 1: `lib/time.ts` — `relativeTimeInStage` helper

**Files:**
- Create: `recruiter-frontend/src/lib/time.ts`
- Create: `recruiter-frontend/src/lib/time.test.ts`

- [ ] **Step 1: Write the failing test**

Create `recruiter-frontend/src/lib/time.test.ts`:

```ts
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { relativeTimeInStage } from "./time";
import type { ApplicationRead } from "@/hooks/use-job-applications";

const NOW = new Date("2026-05-05T12:00:00Z").getTime();

function mkApp(overrides: Partial<ApplicationRead>): ApplicationRead {
  return {
    id: 1, job_id: 1, candidate_id: 1, stage: "scored",
    score: 80, score_breakdown: null, score_rationale: null, notes: null,
    validated_at: null, invited_at: null, scheduled_at: null, rejected_at: null,
    created_at: new Date(NOW).toISOString(),
    updated_at: new Date(NOW).toISOString(),
    awaiting_paste: false,
    ...overrides,
  };
}

describe("relativeTimeInStage", () => {
  beforeEach(() => vi.useFakeTimers().setSystemTime(NOW));
  afterEach(() => vi.useRealTimers());

  it("renders <1m for under 5 minutes", () => {
    const app = mkApp({ created_at: new Date(NOW - 60_000).toISOString() });
    expect(relativeTimeInStage(app)).toEqual({
      label: "<1m", ageingLevel: "fresh",
    });
  });

  it("renders 5h for hours", () => {
    const app = mkApp({ created_at: new Date(NOW - 5 * 3600_000).toISOString() });
    expect(relativeTimeInStage(app).label).toBe("5h");
    expect(relativeTimeInStage(app).ageingLevel).toBe("fresh");
  });

  it("renders Nd for days, fresh < 7d", () => {
    const app = mkApp({ created_at: new Date(NOW - 3 * 86400_000).toISOString() });
    expect(relativeTimeInStage(app).label).toBe("3d");
    expect(relativeTimeInStage(app).ageingLevel).toBe("fresh");
  });

  it("flags warning at 7-14 days", () => {
    const app = mkApp({ created_at: new Date(NOW - 10 * 86400_000).toISOString() });
    expect(relativeTimeInStage(app).label).toBe("10d");
    expect(relativeTimeInStage(app).ageingLevel).toBe("warning");
  });

  it("flags critical at >14 days", () => {
    const app = mkApp({ created_at: new Date(NOW - 20 * 86400_000).toISOString() });
    expect(relativeTimeInStage(app).label).toBe("20d");
    expect(relativeTimeInStage(app).ageingLevel).toBe("critical");
  });

  it("uses validated_at for validated stage", () => {
    const app = mkApp({
      stage: "validated",
      created_at: new Date(NOW - 30 * 86400_000).toISOString(),
      validated_at: new Date(NOW - 2 * 86400_000).toISOString(),
    });
    // 2d since stage entry, not 30d since creation.
    expect(relativeTimeInStage(app).label).toBe("2d");
  });

  it("falls back to created_at when stage timestamp is null", () => {
    const app = mkApp({
      stage: "validated",
      created_at: new Date(NOW - 5 * 86400_000).toISOString(),
      validated_at: null,
    });
    expect(relativeTimeInStage(app).label).toBe("5d");
  });

  it("returns em-dash when all timestamps null", () => {
    const app = mkApp({
      stage: "extracting",
      created_at: null as unknown as string,
    });
    expect(relativeTimeInStage(app).label).toBe("—");
  });
});
```

- [ ] **Step 2: Run, verify fail**

Run: `cd recruiter-frontend && npm run test -- src/lib/time.test.ts`
Expected: collection error — module doesn't exist.

- [ ] **Step 3: Implement**

Create `recruiter-frontend/src/lib/time.ts`:

```ts
import type { ApplicationRead } from "@/hooks/use-job-applications";

export type AgeingLevel = "fresh" | "warning" | "critical";

const STAGE_TIMESTAMP: Record<ApplicationRead["stage"], keyof ApplicationRead | null> = {
  sourced: null,
  extracting: null,
  scored: null,
  validated: "validated_at",
  invited: "invited_at",
  scheduled: "scheduled_at",
  rejected: "rejected_at",
};

function pickStageTimestamp(app: ApplicationRead): string | null {
  const key = STAGE_TIMESTAMP[app.stage];
  if (key) {
    const value = app[key];
    if (typeof value === "string") return value;
  }
  return app.created_at ?? null;
}

function ageingLevel(elapsedMs: number): AgeingLevel {
  const days = elapsedMs / 86_400_000;
  if (days >= 14) return "critical";
  if (days >= 7) return "warning";
  return "fresh";
}

function formatLabel(elapsedMs: number): string {
  if (elapsedMs < 5 * 60_000) return "<1m";
  if (elapsedMs < 3600_000) {
    const m = Math.floor(elapsedMs / 60_000);
    return `${m}m`;
  }
  if (elapsedMs < 86_400_000) {
    const h = Math.floor(elapsedMs / 3600_000);
    return `${h}h`;
  }
  const d = Math.floor(elapsedMs / 86_400_000);
  return `${d}d`;
}

export function relativeTimeInStage(app: ApplicationRead): {
  label: string;
  ageingLevel: AgeingLevel;
} {
  const ts = pickStageTimestamp(app);
  if (!ts) return { label: "—", ageingLevel: "fresh" };
  const elapsed = Date.now() - new Date(ts).getTime();
  if (elapsed < 0) return { label: "<1m", ageingLevel: "fresh" };
  return { label: formatLabel(elapsed), ageingLevel: ageingLevel(elapsed) };
}
```

- [ ] **Step 4: Run, verify pass**

Run: `cd recruiter-frontend && npm run test -- src/lib/time.test.ts`
Expected: 8 PASS.

Run: `cd recruiter-frontend && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
cd /home/walidboudiche/recruiter-agent
git add recruiter-frontend/src/lib/time.ts recruiter-frontend/src/lib/time.test.ts
git commit -m "feat(frontend): relativeTimeInStage helper for ageing kanban cards"
```

---

## Task 2: `TimeInStageBadge` component + integrate into `CandidateCard`

**Files:**
- Create: `recruiter-frontend/src/components/time-in-stage-badge.tsx`
- Create: `recruiter-frontend/src/components/time-in-stage-badge.test.tsx`
- Modify: `recruiter-frontend/src/components/kanban/candidate-card.tsx`

- [ ] **Step 1: Write the failing test**

Create `recruiter-frontend/src/components/time-in-stage-badge.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { TimeInStageBadge } from "./time-in-stage-badge";
import type { ApplicationRead } from "@/hooks/use-job-applications";

const NOW = new Date("2026-05-05T12:00:00Z").getTime();

function mkApp(daysAgo: number, stage: ApplicationRead["stage"] = "scored"): ApplicationRead {
  const ts = new Date(NOW - daysAgo * 86_400_000).toISOString();
  return {
    id: 1, job_id: 1, candidate_id: 1, stage,
    score: null, score_breakdown: null, score_rationale: null, notes: null,
    validated_at: null, invited_at: null, scheduled_at: null, rejected_at: null,
    created_at: ts, updated_at: ts, awaiting_paste: false,
  };
}

describe("TimeInStageBadge", () => {
  beforeEach(() => vi.useFakeTimers().setSystemTime(NOW));
  afterEach(() => vi.useRealTimers());

  it("renders fresh label with muted color under 7d", () => {
    render(<TimeInStageBadge application={mkApp(3)} />);
    const el = screen.getByText("3d");
    expect(el.className).toContain("text-muted-foreground");
  });

  it("renders warning color at 7-14d", () => {
    render(<TimeInStageBadge application={mkApp(10)} />);
    const el = screen.getByText("10d");
    expect(el.className).toContain("text-yellow-600");
  });

  it("renders critical color at >14d", () => {
    render(<TimeInStageBadge application={mkApp(20)} />);
    const el = screen.getByText("20d");
    expect(el.className).toContain("text-red-600");
  });
});
```

- [ ] **Step 2: Run, verify fail**

Run: `cd recruiter-frontend && npm run test -- src/components/time-in-stage-badge.test.tsx`
Expected: collection error — file doesn't exist.

- [ ] **Step 3: Implement the badge**

Create `recruiter-frontend/src/components/time-in-stage-badge.tsx`:

```tsx
import { relativeTimeInStage } from "@/lib/time";
import type { ApplicationRead } from "@/hooks/use-job-applications";

const COLOR: Record<"fresh" | "warning" | "critical", string> = {
  fresh: "text-muted-foreground",
  warning: "text-yellow-600",
  critical: "text-red-600",
};

interface Props {
  application: ApplicationRead;
}

export function TimeInStageBadge({ application }: Props) {
  const { label, ageingLevel } = relativeTimeInStage(application);
  return (
    <span className={`text-[10px] tabular-nums ${COLOR[ageingLevel]}`}>
      {label}
    </span>
  );
}
```

- [ ] **Step 4: Mount in CandidateCard**

Edit `recruiter-frontend/src/components/kanban/candidate-card.tsx`. Add the import:

```tsx
import { TimeInStageBadge } from "@/components/time-in-stage-badge";
```

Find the line that renders the stage label inside the card body:

```tsx
<p className="text-xs text-muted-foreground capitalize">
  {application.stage}
</p>
```

Replace with:

```tsx
<div className="flex items-center justify-between text-xs">
  <span className="text-muted-foreground capitalize">{application.stage}</span>
  <TimeInStageBadge application={application} />
</div>
```

- [ ] **Step 5: Run, verify pass**

Run: `cd recruiter-frontend && npm run test`
Expected: full suite green (existing 37 + 3 new = 40).

Run: `cd recruiter-frontend && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
cd /home/walidboudiche/recruiter-agent
git add recruiter-frontend/src/components/time-in-stage-badge.tsx \
        recruiter-frontend/src/components/time-in-stage-badge.test.tsx \
        recruiter-frontend/src/components/kanban/candidate-card.tsx
git commit -m "feat(frontend): TimeInStageBadge — ageing color tiers on kanban cards"
```

---

## Task 3: Density toggle (comfortable / compact)

**Files:**
- Create: `recruiter-frontend/src/components/kanban/kanban-density-toggle.tsx`
- Create: `recruiter-frontend/src/components/kanban/kanban-density-toggle.test.tsx`
- Modify: `recruiter-frontend/src/routes/job-detail.tsx`
- Modify: `recruiter-frontend/src/components/kanban/kanban-board.tsx`
- Modify: `recruiter-frontend/src/components/kanban/kanban-column.tsx`
- Modify: `recruiter-frontend/src/components/kanban/candidate-card.tsx`

- [ ] **Step 1: Write the failing test**

Create `recruiter-frontend/src/components/kanban/kanban-density-toggle.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { KanbanDensityToggle } from "./kanban-density-toggle";

describe("KanbanDensityToggle", () => {
  beforeEach(() => localStorage.clear());

  it("renders both options and reflects value", () => {
    const { rerender } = render(
      <KanbanDensityToggle value="comfortable" onChange={() => {}} />
    );
    const compact = screen.getByRole("button", { name: /compact/i });
    const comfortable = screen.getByRole("button", { name: /comfortable/i });
    // The selected one should be variant="default" (the unselected ones use outline);
    // we check via aria-pressed instead so we don't depend on Tailwind classes.
    expect(comfortable.getAttribute("aria-pressed")).toBe("true");
    expect(compact.getAttribute("aria-pressed")).toBe("false");

    rerender(<KanbanDensityToggle value="compact" onChange={() => {}} />);
    expect(compact.getAttribute("aria-pressed")).toBe("true");
  });

  it("fires onChange when clicked", () => {
    let value = "comfortable";
    render(
      <KanbanDensityToggle
        value={value as "comfortable" | "compact"}
        onChange={(v) => (value = v)}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /compact/i }));
    expect(value).toBe("compact");
  });
});
```

- [ ] **Step 2: Run, verify fail**

Run: `cd recruiter-frontend && npm run test -- src/components/kanban/kanban-density-toggle.test.tsx`
Expected: collection error.

- [ ] **Step 3: Implement the toggle**

Create `recruiter-frontend/src/components/kanban/kanban-density-toggle.tsx`:

```tsx
import { Button } from "@/components/ui/button";

export type Density = "comfortable" | "compact";

interface Props {
  value: Density;
  onChange: (density: Density) => void;
}

export function KanbanDensityToggle({ value, onChange }: Props) {
  return (
    <div className="inline-flex gap-1">
      <Button
        type="button"
        variant={value === "comfortable" ? "default" : "outline"}
        size="sm"
        aria-pressed={value === "comfortable"}
        onClick={() => onChange("comfortable")}
      >
        Comfortable
      </Button>
      <Button
        type="button"
        variant={value === "compact" ? "default" : "outline"}
        size="sm"
        aria-pressed={value === "compact"}
        onClick={() => onChange("compact")}
      >
        Compact
      </Button>
    </div>
  );
}
```

- [ ] **Step 4: Thread density through KanbanBoard and KanbanColumn**

Edit `recruiter-frontend/src/components/kanban/kanban-board.tsx`. Update the Props interface and column render:

```tsx
import type { Density } from "./kanban-density-toggle";

interface Props {
  applications: ApplicationRead[];
  jobId?: number;
  showRejected?: boolean;
  density?: Density;
}

export function KanbanBoard({ applications, jobId, showRejected = false, density = "comfortable" }: Props) {
  // ... existing logic ...
  // In the JSX, pass density to each KanbanColumn:
  return (
    <DndContext sensors={sensors} onDragEnd={onDragEnd}>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        {columns.map((c) => (
          <KanbanColumn
            key={c.stage}
            title={c.title}
            stage={c.stage}
            applications={grouped.get(c.stage) ?? []}
            density={density}
          />
        ))}
      </div>
    </DndContext>
  );
}
```

Edit `recruiter-frontend/src/components/kanban/kanban-column.tsx`:

```tsx
import { useDroppable } from "@dnd-kit/core";
import { CandidateCard } from "./candidate-card";
import type { Density } from "./kanban-density-toggle";
import type { ApplicationRead } from "@/hooks/use-job-applications";

interface Props {
  title: string;
  stage: ApplicationRead["stage"];
  applications: ApplicationRead[];
  density?: Density;
}

export function KanbanColumn({ title, stage, applications, density = "comfortable" }: Props) {
  const { setNodeRef, isOver } = useDroppable({
    id: `col-${stage}`,
    data: { stage },
  });
  return (
    <div
      ref={setNodeRef}
      className={`flex flex-col rounded-md border bg-muted/30 p-2 min-h-[200px] ${isOver ? "ring-2 ring-primary" : ""}`}
    >
      <header className="px-2 py-1 mb-2 flex items-center justify-between">
        <h3 className="text-sm font-medium">{title}</h3>
        <span className="text-xs text-muted-foreground">{applications.length}</span>
      </header>
      <div className={density === "compact" ? "flex-1 space-y-1" : "flex-1 space-y-2"}>
        {applications.map((app) => (
          <CandidateCard key={app.id} application={app} density={density} />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Add density prop to CandidateCard**

Edit `recruiter-frontend/src/components/kanban/candidate-card.tsx`. Update the Props and apply variant classes:

```tsx
import type { Density } from "./kanban-density-toggle";

interface Props {
  application: ApplicationRead;
  candidateName?: string;
  draggable?: boolean;
  density?: Density;
}

export function CandidateCard({
  application,
  candidateName,
  draggable = true,
  density = "comfortable",
}: Props) {
  // ... existing logic until the Card render ...
  const compact = density === "compact";
  return (
    <Card
      ref={setNodeRef}
      style={style}
      className={`${compact ? "p-1.5" : "p-3"} ${isDragging ? "opacity-50" : ""} ${isDraggable ? "cursor-grab" : ""}${
        application.awaiting_paste ? " border-2 border-yellow-500" : ""
      }`}
      {...(isDraggable ? listeners : {})}
      {...(isDraggable ? attributes : {})}
    >
      <Link to={`/applications/${application.id}`} className="block space-y-1">
        <div className="flex items-center justify-between">
          <span className={`font-medium ${compact ? "text-xs" : "text-sm"} truncate`}>
            {candidateName ?? `Candidate #${application.candidate_id}`}
          </span>
          <ScoreBadge score={application.score} />
        </div>
        {application.awaiting_paste && !compact && (
          <Badge variant="outline" className="text-[10px] border-yellow-500 text-yellow-600">
            Needs profile
          </Badge>
        )}
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted-foreground capitalize">{application.stage}</span>
          <TimeInStageBadge application={application} />
        </div>
      </Link>
    </Card>
  );
}
```

(Note: the `awaiting_paste` border + Badge already exist — preserve them. Just hide the Badge in compact mode to keep cards small.)

- [ ] **Step 6: Wire toggle into job-detail page**

Edit `recruiter-frontend/src/routes/job-detail.tsx`:

```tsx
import { useState } from "react";
import { useParams } from "react-router-dom";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AddCandidatePanel } from "@/components/kanban/add-candidate-panel";
import { KanbanBoard } from "@/components/kanban/kanban-board";
import {
  KanbanDensityToggle,
  type Density,
} from "@/components/kanban/kanban-density-toggle";
import { useJob } from "@/hooks/use-job";
import { useJobApplications } from "@/hooks/use-job-applications";

const DENSITY_KEY = "kanban.density";

function readDensity(): Density {
  try {
    const v = localStorage.getItem(DENSITY_KEY);
    return v === "compact" ? "compact" : "comfortable";
  } catch {
    return "comfortable";
  }
}

export default function JobDetail() {
  const { jobId } = useParams<{ jobId: string }>();
  const id = Number(jobId);
  const job = useJob(id);
  const apps = useJobApplications(id);
  const [showRejected, setShowRejected] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [density, setDensity] = useState<Density>(readDensity);

  function changeDensity(d: Density) {
    setDensity(d);
    try { localStorage.setItem(DENSITY_KEY, d); } catch { /* ignore */ }
  }

  if (job.isLoading || apps.isLoading) return <p>Loading…</p>;
  if (job.isError) return <p className="text-destructive">Failed to load job.</p>;
  if (!job.data) return <p>Job not found.</p>;

  return (
    <div className="space-y-4">
      <header className="flex items-baseline justify-between">
        <div>
          <h2 className="text-xl font-semibold">{job.data.title}</h2>
          <p className="text-sm text-muted-foreground">{job.data.status}</p>
        </div>
        <div className="flex gap-2 items-center">
          <KanbanDensityToggle value={density} onChange={changeDensity} />
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowRejected((s) => !s)}
          >
            {showRejected ? "Hide rejected" : "Show rejected"}
          </Button>
          <Button size="sm" onClick={() => setAddOpen(true)}>
            <Plus className="h-4 w-4 mr-1" />
            Add candidate
          </Button>
        </div>
      </header>
      <KanbanBoard
        applications={apps.data ?? []}
        jobId={id}
        showRejected={showRejected}
        density={density}
      />
      <AddCandidatePanel jobId={id} open={addOpen} onOpenChange={setAddOpen} />
    </div>
  );
}
```

- [ ] **Step 7: Run, verify pass**

Run: `cd recruiter-frontend && npm run test`
Expected: full suite green at 42 (was 40, +2 new tests).

Run: `cd recruiter-frontend && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
cd /home/walidboudiche/recruiter-agent
git add recruiter-frontend/src/components/kanban/kanban-density-toggle.tsx \
        recruiter-frontend/src/components/kanban/kanban-density-toggle.test.tsx \
        recruiter-frontend/src/components/kanban/kanban-board.tsx \
        recruiter-frontend/src/components/kanban/kanban-column.tsx \
        recruiter-frontend/src/components/kanban/candidate-card.tsx \
        recruiter-frontend/src/routes/job-detail.tsx
git commit -m "feat(frontend): kanban density toggle (comfortable / compact)"
```

---

## Task 4: Score distribution strip on the Scored column

**Files:**
- Create: `recruiter-frontend/src/components/kanban/score-distribution-strip.tsx`
- Create: `recruiter-frontend/src/components/kanban/score-distribution-strip.test.tsx`
- Modify: `recruiter-frontend/src/components/kanban/kanban-column.tsx`

- [ ] **Step 1: Write the failing test**

Create `recruiter-frontend/src/components/kanban/score-distribution-strip.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ScoreDistributionStrip } from "./score-distribution-strip";
import type { ApplicationRead } from "@/hooks/use-job-applications";

function mkApp(id: number, score: number | null, stage: ApplicationRead["stage"] = "scored"): ApplicationRead {
  return {
    id, job_id: 1, candidate_id: id, stage,
    score, score_breakdown: null, score_rationale: null, notes: null,
    validated_at: null, invited_at: null, scheduled_at: null, rejected_at: null,
    created_at: "2026-05-05T00:00:00Z", updated_at: "2026-05-05T00:00:00Z",
    awaiting_paste: false,
  };
}

describe("ScoreDistributionStrip", () => {
  it("renders one tick per scored application", () => {
    const { container } = render(
      <ScoreDistributionStrip applications={[mkApp(1, 80), mkApp(2, 65), mkApp(3, 45)]} />
    );
    expect(container.querySelectorAll("rect").length).toBe(3);
  });

  it("renders nothing when applications is empty", () => {
    const { container } = render(<ScoreDistributionStrip applications={[]} />);
    expect(container.querySelector("svg")).toBeNull();
  });

  it("has a tick for each score band color (red < 50, yellow 50-79, green >= 80)", () => {
    const { container } = render(
      <ScoreDistributionStrip applications={[mkApp(1, 90), mkApp(2, 60), mkApp(3, 30)]} />
    );
    const fills = Array.from(container.querySelectorAll("rect")).map(
      (r) => r.getAttribute("fill")
    );
    // Three distinct fills, one per band.
    expect(new Set(fills).size).toBe(3);
  });
});
```

- [ ] **Step 2: Run, verify fail**

Run: `cd recruiter-frontend && npm run test -- src/components/kanban/score-distribution-strip.test.tsx`
Expected: collection error.

- [ ] **Step 3: Implement**

Create `recruiter-frontend/src/components/kanban/score-distribution-strip.tsx`:

```tsx
import type { ApplicationRead } from "@/hooks/use-job-applications";

const STRIP_HEIGHT = 6;
const TICK_WIDTH = 2;

interface Props {
  applications: ApplicationRead[];
}

function colorForScore(score: number): string {
  if (score >= 80) return "#16a34a";   // green-600
  if (score >= 50) return "#ca8a04";   // yellow-600
  return "#dc2626";                    // red-600
}

export function ScoreDistributionStrip({ applications }: Props) {
  if (applications.length === 0) return null;
  return (
    <svg
      className="w-full"
      height={STRIP_HEIGHT}
      preserveAspectRatio="none"
      viewBox={`0 0 100 ${STRIP_HEIGHT}`}
      aria-label="score distribution"
    >
      {applications.map((app) => {
        const score = app.score ?? 0;
        const x = Math.max(0, Math.min(100 - TICK_WIDTH, score - TICK_WIDTH / 2));
        return (
          <rect
            key={app.id}
            x={x}
            y={0}
            width={TICK_WIDTH}
            height={STRIP_HEIGHT}
            fill={colorForScore(score)}
            opacity={app.score === null ? 0.5 : 1}
          >
            <title>{`Candidate #${app.candidate_id}: ${app.score ?? "—"}`}</title>
          </rect>
        );
      })}
    </svg>
  );
}
```

- [ ] **Step 4: Mount in KanbanColumn (Scored only)**

Edit `recruiter-frontend/src/components/kanban/kanban-column.tsx`. Add the import and render:

```tsx
import { ScoreDistributionStrip } from "./score-distribution-strip";
```

After the existing `<header>` block and before the cards container, add:

```tsx
{stage === "scored" && applications.length > 0 && (
  <div className="px-2 mb-2">
    <ScoreDistributionStrip applications={applications} />
  </div>
)}
```

- [ ] **Step 5: Run, verify pass**

Run: `cd recruiter-frontend && npm run test`
Expected: full suite green at 45 (was 42, +3 new tests).

Run: `cd recruiter-frontend && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
cd /home/walidboudiche/recruiter-agent
git add recruiter-frontend/src/components/kanban/score-distribution-strip.tsx \
        recruiter-frontend/src/components/kanban/score-distribution-strip.test.tsx \
        recruiter-frontend/src/components/kanban/kanban-column.tsx
git commit -m "feat(frontend): score distribution strip on Scored column"
```

---

## Task 5: `useKanbanSelection` hook

**Files:**
- Create: `recruiter-frontend/src/hooks/use-kanban-selection.ts`
- Create: `recruiter-frontend/src/hooks/use-kanban-selection.test.ts`

- [ ] **Step 1: Write the failing test**

Create `recruiter-frontend/src/hooks/use-kanban-selection.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useKanbanSelection } from "./use-kanban-selection";

describe("useKanbanSelection", () => {
  it("starts empty", () => {
    const { result } = renderHook(() => useKanbanSelection());
    expect(result.current.selected.size).toBe(0);
  });

  it("toggle adds and removes", () => {
    const { result } = renderHook(() => useKanbanSelection());
    act(() => result.current.toggle(1));
    expect(result.current.selected.has(1)).toBe(true);
    act(() => result.current.toggle(1));
    expect(result.current.selected.has(1)).toBe(false);
  });

  it("selectMany adds all (idempotent)", () => {
    const { result } = renderHook(() => useKanbanSelection());
    act(() => result.current.selectMany([1, 2, 3]));
    expect(result.current.selected.size).toBe(3);
    act(() => result.current.selectMany([2, 3, 4]));
    expect(result.current.selected.size).toBe(4);
  });

  it("clear empties", () => {
    const { result } = renderHook(() => useKanbanSelection());
    act(() => result.current.selectMany([1, 2, 3]));
    act(() => result.current.clear());
    expect(result.current.selected.size).toBe(0);
  });
});
```

- [ ] **Step 2: Run, verify fail**

Run: `cd recruiter-frontend && npm run test -- src/hooks/use-kanban-selection.test.ts`
Expected: collection error.

- [ ] **Step 3: Implement**

Create `recruiter-frontend/src/hooks/use-kanban-selection.ts`:

```ts
import { useCallback, useState } from "react";

export interface SelectionApi {
  selected: Set<number>;
  toggle: (id: number) => void;
  selectMany: (ids: number[]) => void;
  clear: () => void;
}

export function useKanbanSelection(): SelectionApi {
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const toggle = useCallback((id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectMany = useCallback((ids: number[]) => {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const id of ids) next.add(id);
      return next;
    });
  }, []);

  const clear = useCallback(() => setSelected(new Set()), []);

  return { selected, toggle, selectMany, clear };
}
```

- [ ] **Step 4: Run, verify pass**

Run: `cd recruiter-frontend && npm run test -- src/hooks/use-kanban-selection.test.ts`
Expected: 4 PASS.

Run: `cd recruiter-frontend && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
cd /home/walidboudiche/recruiter-agent
git add recruiter-frontend/src/hooks/use-kanban-selection.ts \
        recruiter-frontend/src/hooks/use-kanban-selection.test.ts
git commit -m "feat(frontend): useKanbanSelection hook for multi-select state"
```

---

## Task 6: Multi-select UI + BulkActionsBar

**Files:**
- Create: `recruiter-frontend/src/components/kanban/bulk-actions-bar.tsx`
- Create: `recruiter-frontend/src/components/kanban/bulk-actions-bar.test.tsx`
- Modify: `recruiter-frontend/src/components/kanban/candidate-card.tsx`
- Modify: `recruiter-frontend/src/components/kanban/kanban-board.tsx`
- Modify: `recruiter-frontend/src/components/kanban/kanban-column.tsx`

- [ ] **Step 1: Write the failing test**

Create `recruiter-frontend/src/components/kanban/bulk-actions-bar.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { BulkActionsBar } from "./bulk-actions-bar";
import type { ApplicationRead } from "@/hooks/use-job-applications";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function wrap() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function mkApp(id: number, stage: ApplicationRead["stage"] = "scored"): ApplicationRead {
  return {
    id, job_id: 1, candidate_id: id, stage,
    score: 80, score_breakdown: null, score_rationale: null, notes: null,
    validated_at: null, invited_at: null, scheduled_at: null, rejected_at: null,
    created_at: "2026-05-05T00:00:00Z", updated_at: "2026-05-05T00:00:00Z",
    awaiting_paste: false,
  };
}

describe("BulkActionsBar", () => {
  it("returns null when selection is empty", () => {
    const Wrapper = wrap();
    const { container } = render(
      <Wrapper>
        <BulkActionsBar selected={new Set()} applications={[]} jobId={1} onClear={() => {}} />
      </Wrapper>
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders count + Validate + Reject + Clear when selection non-empty", () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <BulkActionsBar
          selected={new Set([1, 2])}
          applications={[mkApp(1), mkApp(2)]}
          jobId={1}
          onClear={() => {}}
        />
      </Wrapper>
    );
    expect(screen.getByText(/2 selected/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /validate/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reject/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /clear/i })).toBeInTheDocument();
  });

  it("Validate fires N PATCH calls and clears selection on all-success", async () => {
    const calls: number[] = [];
    server.use(
      http.patch("http://localhost:8000/api/applications/:id", async ({ params }) => {
        calls.push(Number(params.id));
        return HttpResponse.json({ id: Number(params.id), stage: "validated" });
      }),
    );
    let cleared = false;
    const Wrapper = wrap();
    render(
      <Wrapper>
        <BulkActionsBar
          selected={new Set([1, 2])}
          applications={[mkApp(1), mkApp(2)]}
          jobId={1}
          onClear={() => { cleared = true; }}
        />
      </Wrapper>
    );
    fireEvent.click(screen.getByRole("button", { name: /validate/i }));
    await waitFor(() => expect(calls.sort()).toEqual([1, 2]));
    await waitFor(() => expect(cleared).toBe(true));
  });
});
```

- [ ] **Step 2: Run, verify fail**

Run: `cd recruiter-frontend && npm run test -- src/components/kanban/bulk-actions-bar.test.tsx`
Expected: collection error.

- [ ] **Step 3: Implement BulkActionsBar**

Create `recruiter-frontend/src/components/kanban/bulk-actions-bar.tsx`:

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import type { ApplicationRead } from "@/hooks/use-job-applications";

interface Props {
  selected: Set<number>;
  applications: ApplicationRead[];
  jobId: number;
  onClear: () => void;
}

async function patchOne(id: number, stage: "validated" | "rejected"): Promise<number> {
  await api(`/api/applications/${id}`, { method: "PATCH", json: { stage } });
  return id;
}

export function BulkActionsBar({ selected, applications, jobId, onClear }: Props) {
  const qc = useQueryClient();

  const validateMut = useMutation({
    mutationFn: async () => {
      const results = await Promise.allSettled(
        [...selected].map((id) => patchOne(id, "validated"))
      );
      return results;
    },
    onSettled: (results) => {
      qc.invalidateQueries({ queryKey: queryKeys.jobApplications(jobId) });
      const failures = (results ?? []).filter((r) => r.status === "rejected");
      if (failures.length === 0) {
        toast.success(`Validated ${selected.size} application${selected.size === 1 ? "" : "s"}`);
        onClear();
      } else {
        for (const r of failures) {
          if (r.status === "rejected") {
            const detail = r.reason instanceof ApiError ? r.reason.detail : "Validate failed";
            toast.error(detail);
          }
        }
      }
    },
  });

  const rejectMut = useMutation({
    mutationFn: async () => {
      const results = await Promise.allSettled(
        [...selected].map((id) => patchOne(id, "rejected"))
      );
      return results;
    },
    onSettled: (results) => {
      qc.invalidateQueries({ queryKey: queryKeys.jobApplications(jobId) });
      const failures = (results ?? []).filter((r) => r.status === "rejected");
      if (failures.length === 0) {
        toast.success(`Rejected ${selected.size} application${selected.size === 1 ? "" : "s"}`);
        onClear();
      } else {
        for (const r of failures) {
          if (r.status === "rejected") {
            const detail = r.reason instanceof ApiError ? r.reason.detail : "Reject failed";
            toast.error(detail);
          }
        }
      }
    },
  });

  if (selected.size === 0) return null;

  // Validate is allowed only for Scored applications.
  const allValidatable = [...selected].every(
    (id) => applications.find((a) => a.id === id)?.stage === "scored"
  );

  const pending = validateMut.isPending || rejectMut.isPending;

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 bg-background border shadow-lg rounded-full px-4 py-2 text-sm">
      <span className="font-medium">{selected.size} selected</span>
      <Button
        size="sm"
        onClick={() => validateMut.mutate()}
        disabled={!allValidatable || pending}
      >
        Validate
      </Button>
      <Button
        size="sm"
        variant="destructive"
        onClick={() => {
          if (selected.size >= 3) {
            const ok = window.confirm(
              `Reject ${selected.size} applications? This cannot be undone via bulk action.`
            );
            if (!ok) return;
          }
          rejectMut.mutate();
        }}
        disabled={pending}
      >
        Reject
      </Button>
      <Button size="sm" variant="ghost" onClick={onClear} disabled={pending}>
        Clear
      </Button>
    </div>
  );
}
```

- [ ] **Step 4: Add selected + onShiftClick to CandidateCard**

Edit `recruiter-frontend/src/components/kanban/candidate-card.tsx`. Update Props and the Link:

```tsx
interface Props {
  application: ApplicationRead;
  candidateName?: string;
  draggable?: boolean;
  density?: Density;
  selected?: boolean;
  onShiftClick?: (id: number) => void;
}

export function CandidateCard({
  application,
  candidateName,
  draggable = true,
  density = "comfortable",
  selected = false,
  onShiftClick,
}: Props) {
  // ... existing logic up to the Card render ...
  const compact = density === "compact";
  const ringClass = selected ? " ring-2 ring-primary/50" : "";

  function handleClick(e: React.MouseEvent) {
    if (e.shiftKey && onShiftClick) {
      e.preventDefault();
      onShiftClick(application.id);
    }
  }

  return (
    <Card
      ref={setNodeRef}
      style={style}
      className={`${compact ? "p-1.5" : "p-3"} ${isDragging ? "opacity-50" : ""} ${isDraggable ? "cursor-grab" : ""}${
        application.awaiting_paste ? " border-2 border-yellow-500" : ""
      }${ringClass}`}
      {...(isDraggable ? listeners : {})}
      {...(isDraggable ? attributes : {})}
    >
      <Link
        to={`/applications/${application.id}`}
        onClick={handleClick}
        className="block space-y-1"
      >
        {/* ... existing inner content unchanged ... */}
      </Link>
    </Card>
  );
}
```

- [ ] **Step 5: Wire selection through KanbanBoard + KanbanColumn**

Edit `recruiter-frontend/src/components/kanban/kanban-board.tsx`. Add state + render BulkActionsBar:

```tsx
import { useKanbanSelection } from "@/hooks/use-kanban-selection";
import { BulkActionsBar } from "./bulk-actions-bar";

// ... inside the component:
const selection = useKanbanSelection();

// At the end of the JSX, after the </DndContext>, render the bar.
// Wrap the existing returned JSX in a fragment if needed:
return (
  <>
    <DndContext sensors={sensors} onDragEnd={onDragEnd}>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        {columns.map((c) => (
          <KanbanColumn
            key={c.stage}
            title={c.title}
            stage={c.stage}
            applications={grouped.get(c.stage) ?? []}
            density={density}
            selected={selection.selected}
            onShiftClick={selection.toggle}
          />
        ))}
      </div>
    </DndContext>
    {jobId !== undefined && (
      <BulkActionsBar
        selected={selection.selected}
        applications={applications}
        jobId={jobId}
        onClear={selection.clear}
      />
    )}
  </>
);
```

Edit `recruiter-frontend/src/components/kanban/kanban-column.tsx`. Add props + thread through:

```tsx
interface Props {
  title: string;
  stage: ApplicationRead["stage"];
  applications: ApplicationRead[];
  density?: Density;
  selected?: Set<number>;
  onShiftClick?: (id: number) => void;
}

export function KanbanColumn({
  title, stage, applications, density = "comfortable",
  selected, onShiftClick,
}: Props) {
  // ... existing droppable + header ...
  return (
    <div /* ...existing... */>
      <header /* ...existing... */ />
      {stage === "scored" && applications.length > 0 && (
        <div className="px-2 mb-2">
          <ScoreDistributionStrip applications={applications} />
        </div>
      )}
      <div className={density === "compact" ? "flex-1 space-y-1" : "flex-1 space-y-2"}>
        {applications.map((app) => (
          <CandidateCard
            key={app.id}
            application={app}
            density={density}
            selected={selected?.has(app.id) ?? false}
            onShiftClick={onShiftClick}
          />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Run, verify pass**

Run: `cd recruiter-frontend && npm run test`
Expected: full suite green at 48 (was 45, +3 new bulk-actions-bar tests).

Run: `cd recruiter-frontend && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
cd /home/walidboudiche/recruiter-agent
git add recruiter-frontend/src/components/kanban/bulk-actions-bar.tsx \
        recruiter-frontend/src/components/kanban/bulk-actions-bar.test.tsx \
        recruiter-frontend/src/components/kanban/candidate-card.tsx \
        recruiter-frontend/src/components/kanban/kanban-board.tsx \
        recruiter-frontend/src/components/kanban/kanban-column.tsx
git commit -m "feat(frontend): kanban multi-select + BulkActionsBar"
```

---

## Task 7: Cmd+K command palette + AppShell trigger

**Files:**
- Create: `recruiter-frontend/src/components/command-palette/command-palette.tsx`
- Create: `recruiter-frontend/src/components/command-palette/command-palette-context.tsx`
- Create: `recruiter-frontend/src/components/command-palette/search-trigger.tsx`
- Create: `recruiter-frontend/src/components/command-palette/command-palette.test.tsx`
- Modify: `recruiter-frontend/src/components/layout/app-shell.tsx`
- Modify: `recruiter-frontend/src/routes/application-detail.tsx`

This task uses the existing `Dialog` shadcn primitive — no new dep — and a simple filtered list.

- [ ] **Step 1: Write the failing test**

Create `recruiter-frontend/src/components/command-palette/command-palette.test.tsx`:

```tsx
import { describe, it, expect, vi, afterEach, beforeAll, afterAll } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { CommandPaletteProvider, useCommandPalette } from "./command-palette-context";
import { CommandPalette } from "./command-palette";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  localStorage.clear();
});
afterAll(() => server.close());

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CommandPaletteProvider>{children}</CommandPaletteProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function Opener() {
  const ctx = useCommandPalette();
  return <button onClick={() => ctx.setOpen(true)}>open palette</button>;
}

describe("CommandPalette", () => {
  it("opens via the context setter and lists jobs", async () => {
    server.use(
      http.get("http://localhost:8000/api/jobs", () =>
        HttpResponse.json([
          { id: 1, title: "Backend", description: "x", criteria: [], status: "open",
            created_at: "2026-05-05T00:00:00Z", updated_at: "2026-05-05T00:00:00Z" },
        ]),
      ),
    );
    const Wrapper = wrap();
    render(
      <Wrapper>
        <Opener />
        <CommandPalette />
      </Wrapper>
    );
    fireEvent.click(screen.getByText(/open palette/i));
    await screen.findByText("Backend");
  });

  it("opens via Cmd+K keydown", async () => {
    server.use(
      http.get("http://localhost:8000/api/jobs", () => HttpResponse.json([])),
    );
    const Wrapper = wrap();
    render(
      <Wrapper>
        <Opener />
        <CommandPalette />
      </Wrapper>
    );
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    // The search input becomes visible.
    await screen.findByPlaceholderText(/search/i);
  });
});
```

- [ ] **Step 2: Run, verify fail**

Run: `cd recruiter-frontend && npm run test -- src/components/command-palette/command-palette.test.tsx`
Expected: collection error.

- [ ] **Step 3: Create the context**

Create `recruiter-frontend/src/components/command-palette/command-palette-context.tsx`:

```tsx
import { createContext, useContext, useEffect, useMemo, useState } from "react";

interface CommandPaletteApi {
  open: boolean;
  setOpen: (open: boolean) => void;
  toggle: () => void;
}

const Ctx = createContext<CommandPaletteApi | null>(null);

export function CommandPaletteProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const value = useMemo<CommandPaletteApi>(
    () => ({ open, setOpen, toggle: () => setOpen((o) => !o) }),
    [open],
  );

  // Global Cmd+K / Ctrl+K binding.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const isMac = navigator.platform.toLowerCase().includes("mac");
      const mod = isMac ? e.metaKey : e.ctrlKey;
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
      if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCommandPalette(): CommandPaletteApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("useCommandPalette must be inside <CommandPaletteProvider>");
  return v;
}

const RECENT_KEY = "recent.applications";

export interface RecentApp {
  id: number;
  name: string;
  ts: number;
}

export function pushRecentApp(entry: RecentApp): void {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const list: RecentApp[] = raw ? JSON.parse(raw) : [];
    const next = [entry, ...list.filter((e) => e.id !== entry.id)].slice(0, 10);
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* ignore localStorage errors (private mode etc.) */
  }
}

export function readRecentApps(): RecentApp[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}
```

- [ ] **Step 4: Create the modal**

Create `recruiter-frontend/src/components/command-palette/command-palette.tsx`:

```tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { useTheme } from "@/components/theme/theme-provider";
import {
  readRecentApps,
  useCommandPalette,
  type RecentApp,
} from "./command-palette-context";

interface JobItem {
  id: number;
  title: string;
}

interface PaletteItem {
  id: string;
  label: string;
  hint?: string;
  section: string;
  run: () => void;
}

export function CommandPalette() {
  const { open, setOpen } = useCommandPalette();
  const navigate = useNavigate();
  const { setTheme } = useTheme();
  const [query, setQuery] = useState("");

  const jobs = useQuery({
    queryKey: queryKeys.jobs(),
    queryFn: () => api<JobItem[]>("/api/jobs"),
    enabled: open,  // only fetch when palette is open
  });

  const recents: RecentApp[] = open ? readRecentApps() : [];

  const items: PaletteItem[] = [
    ...(jobs.data ?? []).map<PaletteItem>((j) => ({
      id: `job:${j.id}`,
      label: j.title,
      section: "Jobs",
      run: () => { setOpen(false); navigate(`/jobs/${j.id}`); },
    })),
    ...recents.map<PaletteItem>((r) => ({
      id: `recent:${r.id}`,
      label: r.name,
      hint: "Recently viewed application",
      section: "Recent applications",
      run: () => { setOpen(false); navigate(`/applications/${r.id}`); },
    })),
    {
      id: "act:new-job",
      label: "New job",
      section: "Actions",
      run: () => { setOpen(false); navigate("/jobs/new"); },
    },
    {
      id: "act:settings",
      label: "Open settings",
      section: "Settings",
      run: () => { setOpen(false); navigate("/settings"); },
    },
    {
      id: "act:theme-light",
      label: "Switch to light theme",
      section: "Theme",
      run: () => { setOpen(false); setTheme("light"); },
    },
    {
      id: "act:theme-dark",
      label: "Switch to dark theme",
      section: "Theme",
      run: () => { setOpen(false); setTheme("dark"); },
    },
    {
      id: "act:theme-system",
      label: "Match system theme",
      section: "Theme",
      run: () => { setOpen(false); setTheme("system"); },
    },
  ];

  const filtered = query.trim()
    ? items.filter((i) => i.label.toLowerCase().includes(query.toLowerCase()))
    : items;

  // Group by section.
  const grouped = filtered.reduce<Record<string, PaletteItem[]>>((acc, item) => {
    (acc[item.section] ??= []).push(item);
    return acc;
  }, {});

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-lg p-0 overflow-hidden">
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        <div className="border-b p-2">
          <Input
            autoFocus
            placeholder="Search…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="max-h-[60vh] overflow-y-auto p-2">
          {Object.entries(grouped).map(([section, list]) => (
            <div key={section} className="mb-2">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground px-2 mb-1">
                {section}
              </p>
              {list.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className="w-full text-left px-2 py-1.5 rounded text-sm hover:bg-muted"
                  onClick={item.run}
                >
                  {item.label}
                  {item.hint && (
                    <span className="text-xs text-muted-foreground ml-2">{item.hint}</span>
                  )}
                </button>
              ))}
            </div>
          ))}
          {filtered.length === 0 && (
            <p className="text-sm text-muted-foreground p-2">No matches.</p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 5: Create the header trigger**

Create `recruiter-frontend/src/components/command-palette/search-trigger.tsx`:

```tsx
import { Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useCommandPalette } from "./command-palette-context";

export function SearchTrigger() {
  const { setOpen } = useCommandPalette();
  return (
    <Button
      variant="ghost"
      size="sm"
      aria-label="Open command palette"
      onClick={() => setOpen(true)}
    >
      <Search className="h-4 w-4" />
    </Button>
  );
}
```

- [ ] **Step 6: Mount in AppShell**

Edit `recruiter-frontend/src/components/layout/app-shell.tsx`:

```tsx
import { Link, Outlet } from "react-router-dom";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { UserChip } from "@/components/auth/user-chip";
import { CommandPaletteProvider } from "@/components/command-palette/command-palette-context";
import { CommandPalette } from "@/components/command-palette/command-palette";
import { SearchTrigger } from "@/components/command-palette/search-trigger";

export function AppShell() {
  return (
    <CommandPaletteProvider>
      <div className="min-h-screen flex flex-col">
        <header className="border-b">
          <div className="container flex h-14 items-center justify-between">
            <Link to="/jobs" className="text-lg font-semibold">
              Recruiter Agent
            </Link>
            <nav className="flex items-center gap-4">
              <Link to="/jobs" className="text-sm hover:underline">Jobs</Link>
              <Link to="/settings" className="text-sm hover:underline">Settings</Link>
              <SearchTrigger />
              <UserChip />
              <ThemeToggle />
            </nav>
          </div>
        </header>
        <main className="container flex-1 py-6">
          <Outlet />
        </main>
        <CommandPalette />
      </div>
    </CommandPaletteProvider>
  );
}
```

- [ ] **Step 7: Track recent applications on detail mount**

Edit `recruiter-frontend/src/routes/application-detail.tsx`. Add the import and effect:

```tsx
import { useEffect } from "react";
import { pushRecentApp } from "@/components/command-palette/command-palette-context";
```

Inside the component, after the existing data hooks but before the early returns, add:

```tsx
useEffect(() => {
  if (application.data && candidate.data) {
    pushRecentApp({
      id: application.data.id,
      name: candidate.data.full_name ?? `Candidate #${application.data.candidate_id}`,
      ts: Date.now(),
    });
  }
}, [application.data, candidate.data]);
```

- [ ] **Step 8: Run, verify pass**

Run: `cd recruiter-frontend && npm run test`
Expected: full suite green at 50 (was 48, +2 new palette tests).

Run: `cd recruiter-frontend && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
cd /home/walidboudiche/recruiter-agent
git add recruiter-frontend/src/components/command-palette/command-palette.tsx \
        recruiter-frontend/src/components/command-palette/command-palette-context.tsx \
        recruiter-frontend/src/components/command-palette/search-trigger.tsx \
        recruiter-frontend/src/components/command-palette/command-palette.test.tsx \
        recruiter-frontend/src/components/layout/app-shell.tsx \
        recruiter-frontend/src/routes/application-detail.tsx
git commit -m "feat(frontend): Cmd+K command palette + magnifying-glass header trigger"
```

---

## Final verification

After all 7 tasks:

- [ ] `cd recruiter-frontend && npm run test` → 50+ passed
- [ ] `cd recruiter-frontend && npx tsc --noEmit` → clean
- [ ] Manual smoke: open `/jobs/4`, see time badges + density toggle + score distribution strip; shift-click 2 cards → bar appears → Validate works; press Cmd+K → palette opens with jobs; click magnifying-glass icon → same palette opens.

## Known v1 limitations (per design)

- No direct keyboard shortcuts on the kanban (j/k/v/r/n) — explicitly out of scope
- Bulk Reject confirmation uses native `window.confirm` rather than a styled dialog — fine for v1
- Recent applications are localStorage-scoped (per-browser, per-user-on-this-machine); no server-side history
- Density toggle is per-job (each visit reads the same global localStorage key) — not per-job preference
- Score distribution strip tooltip uses native SVG `<title>` (browser tooltip), not a styled overlay
