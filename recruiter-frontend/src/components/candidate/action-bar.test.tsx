import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ActionBar } from "./action-bar";
import type { ApplicationRead } from "@/hooks/use-job-applications";
import { queryKeys } from "@/lib/query-keys";

const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: apiMock };
});

function baseApp(overrides: Partial<ApplicationRead> = {}): ApplicationRead {
  return {
    id: 1, job_id: 1, candidate_id: 1, stage: "scored",
    score: 80, score_breakdown: null, score_rationale: null, notes: null,
    validated_at: null, invited_at: null, scheduled_at: null, rejected_at: null,
    created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    awaiting_paste: false,
    ...overrides,
  };
}

function renderBar(application: ApplicationRead) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ActionBar application={application} candidateEmail="alice@example.com" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiMock.mockReset();
  apiMock.mockImplementation(async (path: string) =>
    path.startsWith("/api/interview-templates") ? [] : {});
});

describe("ActionBar — post-invite stage buttons", () => {
  it("shows only \"Mark as scheduled\" when invited", () => {
    renderBar(baseApp({ stage: "invited" }));
    expect(screen.getByRole("button", { name: /mark as scheduled/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /mark as interviewed/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /extend offer/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /mark as hired/i })).not.toBeInTheDocument();
  });

  it("shows only \"Mark as interviewed\" when scheduled", () => {
    renderBar(baseApp({ stage: "scheduled" }));
    expect(screen.getByRole("button", { name: /mark as interviewed/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /mark as scheduled/i })).not.toBeInTheDocument();
  });

  it("offers another interview round when interviewed", async () => {
    // Without this, a second interview means rejecting the candidate and
    // re-inviting them — see _open_next_round.
    renderBar(baseApp({ stage: "interviewed" }));

    await userEvent.click(screen.getByRole("button", { name: /another round/i }));

    const isPatch = ([, o]: unknown[]) => (o as { method?: string } | undefined)?.method === "PATCH";
    await waitFor(() => expect(apiMock.mock.calls.some(isPatch)).toBe(true));
    const [path, opts] = apiMock.mock.calls.find(isPatch)!;
    expect(path).toBe("/api/applications/1");
    expect(opts).toMatchObject({ method: "PATCH", json: { stage: "scheduled" } });
  });

  it("does not offer another round before the first one has happened", () => {
    renderBar(baseApp({ stage: "scheduled" }));
    expect(screen.queryByRole("button", { name: /another round/i })).not.toBeInTheDocument();
  });

  it("shows only \"Extend offer\" when interviewed", () => {
    renderBar(baseApp({ stage: "interviewed" }));
    expect(screen.getByRole("button", { name: /extend offer/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /mark as interviewed/i })).not.toBeInTheDocument();
  });

  it("shows only \"Mark as hired\" when offer", () => {
    renderBar(baseApp({ stage: "offer" }));
    expect(screen.getByRole("button", { name: /mark as hired/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /extend offer/i })).not.toBeInTheDocument();
  });

  it("shows no forward-stage button once hired", () => {
    renderBar(baseApp({ stage: "hired" }));
    expect(screen.queryByRole("button", { name: /mark as hired/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /extend offer/i })).not.toBeInTheDocument();
  });

  it("allows Reject from scheduled, interviewed and offer, but not once hired", () => {
    for (const stage of ["scheduled", "interviewed", "offer"] as const) {
      const { unmount } = renderBar(baseApp({ stage }));
      expect(screen.getByRole("button", { name: /^reject$/i })).toBeInTheDocument();
      unmount();
    }
    renderBar(baseApp({ stage: "hired" }));
    expect(screen.queryByRole("button", { name: /^reject$/i })).not.toBeInTheDocument();
  });

  it("PATCHes the next stage when \"Mark as scheduled\" is clicked", async () => {
    renderBar(baseApp({ stage: "invited" }));
    await userEvent.click(screen.getByRole("button", { name: /mark as scheduled/i }));
    await waitFor(() =>
      expect(apiMock).toHaveBeenCalledWith("/api/applications/1", {
        method: "PATCH",
        json: { stage: "scheduled" },
      }),
    );
  });

  it("opens the template picker instead of scheduling when templates exist", async () => {
    const technical = { id: 1, name: "Technical", description: null, questions: [],
                        probe_mode: "score_gaps", include_job_questions: true, is_active: true };
    apiMock.mockImplementation(async (path: string) =>
      path.startsWith("/api/interview-templates") ? [technical] : {});
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    qc.setQueryData(queryKeys.interviewTemplates(false), [technical]);
    render(
      <QueryClientProvider client={qc}>
        <ActionBar application={baseApp({ stage: "invited" })} candidateEmail="alice@example.com" />
      </QueryClientProvider>,
    );

    await userEvent.click(screen.getByRole("button", { name: /mark as scheduled/i }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(apiMock.mock.calls.some(([, o]) => o?.method === "PATCH")).toBe(false);
  });

  it("offers the previous round's tracks for another round", async () => {
    const t = (id: number, name: string) => ({ id, name, description: null, questions: [],
      probe_mode: "none", include_job_questions: false, is_active: true });
    const templates = [t(1, "Technical"), t(2, "RH screen"), t(3, "Culture")];
    const kit = { kit: null, sheets: [], tracks: [
      { track: "t1", template_id: 1, template_name: "Technical", kit: { status: "ready", questions: [] } },
      { track: "t2", template_id: 2, template_name: "RH screen", kit: { status: "ready", questions: [] } },
    ] };
    apiMock.mockImplementation(async (path: string) =>
      path.startsWith("/api/interview-templates") ? templates
        : path.endsWith("/interview-kit") ? kit : {});
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    qc.setQueryData(queryKeys.interviewTemplates(false), templates);
    qc.setQueryData(queryKeys.interviewKit(1), kit);
    render(
      <QueryClientProvider client={qc}>
        <ActionBar application={baseApp({ stage: "interviewed" })} candidateEmail="alice@example.com" />
      </QueryClientProvider>,
    );

    await userEvent.click(screen.getByRole("button", { name: /another round/i }));

    expect(await screen.findByRole("checkbox", { name: /^Technical ·/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /^RH screen ·/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /^Culture ·/ })).not.toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: /^schedule$/i }));
    await waitFor(() => expect(apiMock).toHaveBeenCalledWith("/api/applications/1", {
      method: "PATCH", json: { stage: "scheduled", interview_template_ids: [1, 2] },
    }));
  });

  it("preselects the round's own tracks, not the job default, when re-scheduling a round that already has tracks", async () => {
    // Reject -> re-invite -> schedule re-enters this same "invited" stage
    // with the round's kits still standing. The job default must not win:
    // that would silently drop every other track the moment the recruiter
    // confirms the pre-filled dialog.
    const t = (id: number, name: string) => ({ id, name, description: null, questions: [],
      probe_mode: "none", include_job_questions: false, is_active: true });
    const templates = [t(1, "Technical"), t(2, "RH screen"), t(3, "Culture")];
    const kit = { kit: null, sheets: [], tracks: [
      { track: "t1", template_id: 1, template_name: "Technical", kit: { status: "ready", questions: [] } },
      { track: "t2", template_id: 2, template_name: "RH screen", kit: { status: "ready", questions: [] } },
    ] };
    apiMock.mockImplementation(async (path: string) =>
      path.startsWith("/api/interview-templates") ? templates
        : path.endsWith("/interview-kit") ? kit : {});
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    qc.setQueryData(queryKeys.interviewTemplates(false), templates);
    qc.setQueryData(queryKeys.interviewKit(1), kit);
    // The job's default is a THIRD template, distinct from the round's own
    // tracks, so preselecting it would be visibly wrong.
    qc.setQueryData(queryKeys.job(1), { id: 1, default_interview_template_id: 3 });
    render(
      <QueryClientProvider client={qc}>
        <ActionBar application={baseApp({ stage: "invited" })} candidateEmail="alice@example.com" />
      </QueryClientProvider>,
    );

    await userEvent.click(screen.getByRole("button", { name: /mark as scheduled/i }));

    expect(await screen.findByRole("checkbox", { name: /^Technical ·/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /^RH screen ·/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /^Culture ·/ })).not.toBeChecked();
  });
});
