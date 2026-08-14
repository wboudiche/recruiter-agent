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
  const utils = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CandidateCard application={application} jobId={8} draggable={false} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  // Mirrors production: `CandidateCard` is keyed by application id in
  // kanban-column.tsx, so an SSE-triggered refetch re-renders the SAME
  // instance with new `application` props rather than remounting it.
  // Reusing the same QueryClientProvider/MemoryRouter tree (not a fresh
  // render) is what lets useMutation state survive across the rerender,
  // just like it does in the real card.
  function rerenderCard(nextApplication: ApplicationRead) {
    utils.rerender(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <CandidateCard application={nextApplication} jobId={8} draggable={false} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }
  return { ...utils, rerenderCard };
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

  it("disables Retry after a successful click so a second click can't fire a duplicate POST", async () => {
    // last_error stays stale until the NEW pipeline run writes an event
    // 10-60s later, so a naive `isPending`-only disable re-enables the
    // button on refetch while the old error line is still showing. That
    // lets a user fire a second `process_application` background task on
    // top of the first — double LLM spend and duplicate scored events.
    renderCard(baseApp({ last_error: "boom" }));
    const button = screen.getByRole("button", { name: /retry/i });

    await userEvent.click(button);
    await waitFor(() => expect(apiMock).toHaveBeenCalledTimes(1));

    // The mutation has settled (the 202 resolved) but `last_error` on the
    // application prop is still the stale value — nothing has re-fetched
    // a cleared error yet. The button must remain disabled regardless.
    await waitFor(() => expect(button).toBeDisabled());
    await userEvent.click(button, { pointerEventsCheck: 0 });

    expect(apiMock).toHaveBeenCalledTimes(1);
  });

  it("re-enables Retry with the normal label once a genuinely new last_error arrives", async () => {
    // The retried run also failed: SSE invalidation lands a fresh
    // `last_error` (different from the one showing when the user clicked).
    // That's exactly the case Retry exists for, so the button must come
    // back to life instead of staying stuck on "Retrying…" forever.
    const { rerenderCard } = renderCard(baseApp({ last_error: "boom" }));
    const button = screen.getByRole("button", { name: /retry/i });

    await userEvent.click(button);
    await waitFor(() => expect(apiMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(button).toBeDisabled());
    expect(button).toHaveTextContent("Retrying…");

    rerenderCard(baseApp({ last_error: "different failure this time" }));

    await waitFor(() => expect(button).not.toBeDisabled());
    expect(button).toHaveTextContent("Retry");

    await userEvent.click(button);
    await waitFor(() => expect(apiMock).toHaveBeenCalledTimes(2));
  });

  it("stays disabled when last_error is unchanged after a successful retry (still the stale window)", async () => {
    // Nothing proves the new run has actually reported anything yet --
    // the error text is identical to what was showing before the click --
    // so this must NOT be treated as a new failure.
    const { rerenderCard } = renderCard(baseApp({ last_error: "boom" }));
    const button = screen.getByRole("button", { name: /retry/i });

    await userEvent.click(button);
    await waitFor(() => expect(apiMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(button).toBeDisabled());

    rerenderCard(baseApp({ last_error: "boom" }));

    expect(button).toBeDisabled();
    await userEvent.click(button, { pointerEventsCheck: 0 });

    expect(apiMock).toHaveBeenCalledTimes(1);
  });
});
