import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { CandidateCard } from "./candidate-card";
import type { ApplicationRead } from "@/hooks/use-job-applications";

const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: apiMock };
});

function baseApp(overrides: Partial<ApplicationRead> = {}): ApplicationRead {
  return {
    id: 68, job_id: 8, candidate_id: 68, stage: "extracting",
    score: null, score_breakdown: null, score_rationale: null, notes: null,
    validated_at: null, invited_at: null, scheduled_at: null, rejected_at: null,
    created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    awaiting_paste: false, last_error: null,
    ...overrides,
  };
}

function renderCard(application: ApplicationRead) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CandidateCard application={application} jobId={8} draggable={false} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiMock.mockReset();
  apiMock.mockResolvedValue({ application_id: 68 });
});

describe("CandidateCard retry", () => {
  it("shows the failure reason and a Retry button when extraction stalled", () => {
    renderCard(baseApp({ last_error: "HTTP 429 rate-limited upstream" }));

    expect(screen.getByText(/rate-limited upstream/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("shows neither when there is no error", () => {
    renderCard(baseApp());

    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  it("explains the error but hides Retry once the application has moved on", () => {
    // Re-enrich can fail on an already-scored application. Retrying there
    // is a guaranteed 409, so the button must not be offered.
    renderCard(baseApp({ stage: "scored", score: 26, last_error: "enrichment boom" }));

    expect(screen.getByText(/enrichment boom/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  it("posts to the retry endpoint when clicked", async () => {
    renderCard(baseApp({ last_error: "boom" }));

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() =>
      expect(apiMock).toHaveBeenCalledWith("/api/applications/68/retry", { method: "POST" }),
    );
  });
});
