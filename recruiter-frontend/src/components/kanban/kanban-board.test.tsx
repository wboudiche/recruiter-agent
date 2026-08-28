import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import type { ReactNode } from "react";
import { KanbanBoard, isDragAllowed } from "./kanban-board";
import type { ApplicationRead } from "@/hooks/use-job-applications";

// Shift-click selection feeds BulkActionsBar, which PATCHes applications —
// a write path. A viewer must not be able to select cards into a dead end
// (selected with no bar to act on them), and must not see the bar at all.
const server = setupServer(
  http.get("http://localhost:8000/api/candidates/:id", ({ params }) =>
    HttpResponse.json({
      id: Number(params.id),
      full_name: `Candidate ${params.id}`,
      email: null,
      source_url: null,
    }),
  ),
);
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function wrap(children: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
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

describe("KanbanBoard — bulk selection gating", () => {
  it("lets a recruiter shift-click select a card, revealing BulkActionsBar", async () => {
    render(wrap(<KanbanBoard applications={[mkApp(1)]} jobId={1} canWrite={true} />));

    const card = await screen.findByText(/candidate 1/i);
    fireEvent.click(card, { shiftKey: true });

    expect(await screen.findByText(/1 selected/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /validate/i })).toBeInTheDocument();
  });

  it("does not let a viewer select a card or see BulkActionsBar", async () => {
    render(wrap(<KanbanBoard applications={[mkApp(1)]} jobId={1} canWrite={false} />));

    const card = await screen.findByText(/candidate 1/i);
    fireEvent.click(card, { shiftKey: true });

    // Nothing async should ever flip this on; assert against the
    // settled DOM rather than a race against a timer.
    expect(screen.queryByText(/selected/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^validate$/i })).not.toBeInTheDocument();
  });
});

describe("KanbanBoard — post-invite stage columns", () => {
  it("renders a column for each new stage", async () => {
    render(
      wrap(
        <KanbanBoard
          applications={[
            mkApp(1, "scheduled"),
            mkApp(2, "interviewed"),
            mkApp(3, "offer"),
            mkApp(4, "hired"),
          ]}
          jobId={1}
        />,
      ),
    );

    expect(await screen.findByText("Scheduled")).toBeInTheDocument();
    expect(screen.getByText("Interviewed")).toBeInTheDocument();
    expect(screen.getByText("Offer")).toBeInTheDocument();
    expect(screen.getByText("Hired")).toBeInTheDocument();
  });
});

describe("isDragAllowed", () => {
  it("allows scored<->validated", () => {
    expect(isDragAllowed("scored", "validated")).toBe(true);
    expect(isDragAllowed("validated", "scored")).toBe(true);
  });

  it("allows dragging to rejected from any stage except hired", () => {
    expect(isDragAllowed("scored", "rejected")).toBe(true);
    expect(isDragAllowed("scheduled", "rejected")).toBe(true);
    expect(isDragAllowed("offer", "rejected")).toBe(true);
    expect(isDragAllowed("hired", "rejected")).toBe(false);
  });

  it("blocks forward progression by drag (buttons only)", () => {
    expect(isDragAllowed("invited", "scheduled")).toBe(false);
    expect(isDragAllowed("scheduled", "interviewed")).toBe(false);
    expect(isDragAllowed("interviewed", "offer")).toBe(false);
    expect(isDragAllowed("offer", "hired")).toBe(false);
  });
});
