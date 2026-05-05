import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
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
        <BulkActionsBar
          selected={new Set()}
          applications={[]}
          jobId={1}
          setSelected={() => {}}
        />
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
          setSelected={() => {}}
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
    let lastSet: Set<number> | null = null;
    const Wrapper = wrap();
    render(
      <Wrapper>
        <BulkActionsBar
          selected={new Set([1, 2])}
          applications={[mkApp(1), mkApp(2)]}
          jobId={1}
          setSelected={(s) => { lastSet = s; }}
        />
      </Wrapper>
    );
    fireEvent.click(screen.getByRole("button", { name: /validate/i }));
    await waitFor(() => expect(calls.sort()).toEqual([1, 2]));
    await waitFor(() => expect(lastSet?.size).toBe(0));
  });

  it("partial failure narrows selection to the failed ids", async () => {
    server.use(
      http.patch("http://localhost:8000/api/applications/:id", ({ params }) => {
        const id = Number(params.id);
        // App 1 succeeds, app 2 fails.
        if (id === 1) return HttpResponse.json({ id, stage: "validated" });
        return HttpResponse.json({ detail: "boom" }, { status: 500 });
      }),
    );
    let lastSet: Set<number> | null = null;
    const Wrapper = wrap();
    render(
      <Wrapper>
        <BulkActionsBar
          selected={new Set([1, 2])}
          applications={[mkApp(1), mkApp(2)]}
          jobId={1}
          setSelected={(s) => { lastSet = s; }}
        />
      </Wrapper>
    );
    fireEvent.click(screen.getByRole("button", { name: /validate/i }));
    await waitFor(() => {
      expect(lastSet).not.toBeNull();
      expect([...(lastSet ?? new Set())]).toEqual([2]);
    });
  });
});
