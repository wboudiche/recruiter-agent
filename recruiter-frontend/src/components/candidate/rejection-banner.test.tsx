import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RejectionBanner } from "./rejection-banner";
import type { ApplicationRead } from "@/hooks/use-job-applications";

function rejectedApp(overrides: Partial<ApplicationRead> = {}): ApplicationRead {
  return {
    id: 1, job_id: 1, candidate_id: 1, stage: "rejected",
    score: null, score_breakdown: null, score_rationale: null, notes: null,
    validated_at: null, invited_at: null, scheduled_at: null,
    rejected_at: "2026-05-05T00:00:00Z", rejection_reason: "Not a fit",
    created_at: "2026-05-05T00:00:00Z", updated_at: "2026-05-05T00:00:00Z",
    awaiting_paste: false,
    ...overrides,
  };
}

function renderBanner(canWrite?: boolean) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <RejectionBanner application={rejectedApp()} canWrite={canWrite} />
    </QueryClientProvider>,
  );
}

// Unreject PATCHes the application back to "scored" — a write.
describe("RejectionBanner — Unreject", () => {
  it("offers Unreject to a recruiter (canWrite defaults true)", () => {
    renderBanner();
    expect(screen.getByRole("button", { name: /unreject/i })).toBeInTheDocument();
  });

  it("hides Unreject from a viewer", () => {
    renderBanner(false);
    expect(screen.queryByRole("button", { name: /unreject/i })).not.toBeInTheDocument();
  });
});
