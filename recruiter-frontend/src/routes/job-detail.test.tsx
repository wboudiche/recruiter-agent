import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
