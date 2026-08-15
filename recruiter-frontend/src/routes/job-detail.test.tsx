import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import JobDetail from "./job-detail";

const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: apiMock };
});

function mockApiForRole(role: "admin" | "recruiter" | "viewer") {
  apiMock.mockReset();
  apiMock.mockImplementation((path: string) => {
    if (path === "/api/auth/me") {
      return Promise.resolve({ id: 1, email: "u@acme.com", name: null, picture: null, role });
    }
    if (path.startsWith("/api/jobs/8/applications")) return Promise.resolve([]);
    if (path.startsWith("/api/jobs/8")) {
      return Promise.resolve({ id: 8, title: "Senior Data Scientist", description: "d", criteria: [], status: "open" });
    }
    return Promise.resolve([]);
  });
}

function renderJob() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/jobs/8"]}>
        <Routes>
          <Route path="/jobs/:jobId" element={<JobDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => mockApiForRole("recruiter"));

describe("JobDetail write controls", () => {
  it("offers Add candidate to a recruiter", async () => {
    mockApiForRole("recruiter");
    renderJob();

    expect(await screen.findByRole("button", { name: /add candidate/i })).toBeInTheDocument();
  });

  it("hides Add candidate from a viewer", async () => {
    mockApiForRole("viewer");
    renderJob();

    // Wait for the board to settle so this is not just an early render.
    // The title appears twice (breadcrumb + header), so target the
    // heading specifically rather than findByText, which throws on
    // multiple matches.
    await screen.findByRole("heading", { name: /senior data scientist/i });
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /add candidate/i })).not.toBeInTheDocument(),
    );
  });
});

describe("JobDetail write controls — job actions menu", () => {
  it("offers Close job to a recruiter via the Manage menu", async () => {
    mockApiForRole("recruiter");
    renderJob();
    await screen.findByRole("heading", { name: /senior data scientist/i });

    await userEvent.click(screen.getByRole("button", { name: /manage job/i }));

    expect(await screen.findByRole("menuitem", { name: /close job/i })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /^edit details$/i })).toBeInTheDocument();
  });

  it("hides Close job from a viewer, offering View details instead", async () => {
    mockApiForRole("viewer");
    renderJob();
    await screen.findByRole("heading", { name: /senior data scientist/i });

    await userEvent.click(screen.getByRole("button", { name: /manage job/i }));

    expect(await screen.findByRole("menuitem", { name: /view details/i })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /close job/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /^edit details$/i })).not.toBeInTheDocument();
  });
});

describe("JobDetail write controls — criteria sheet", () => {
  it("shows Save, Suggest from JD, and Add criterion to a recruiter", async () => {
    mockApiForRole("recruiter");
    renderJob();
    await screen.findByRole("heading", { name: /senior data scientist/i });

    await userEvent.click(screen.getByRole("button", { name: /^criteria/i }));

    expect(await screen.findByRole("heading", { name: /^edit criteria$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /suggest from jd/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add criterion/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^save$/i })).toBeInTheDocument();
  });

  it("shows the criteria sheet read-only to a viewer, without Save, Suggest, or Add", async () => {
    mockApiForRole("viewer");
    renderJob();
    await screen.findByRole("heading", { name: /senior data scientist/i });

    await userEvent.click(screen.getByRole("button", { name: /^criteria/i }));

    // Still reachable — a viewer is entitled to see what a job is scored
    // against — just without any control that would only 403.
    expect(await screen.findByRole("heading", { name: /^criteria$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /suggest from jd/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add criterion/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^save$/i })).not.toBeInTheDocument();
  });
});
