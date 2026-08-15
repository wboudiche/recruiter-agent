import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import JobsList from "./jobs-list";

function job(id: number, title: string) {
  return {
    id, title, description: "d", criteria: [], status: "open",
    created_at: "2026-05-05T00:00:00Z", updated_at: "2026-05-05T00:00:00Z",
  };
}

const server = setupServer(
  http.get("http://localhost:8000/api/jobs", () =>
    HttpResponse.json([job(1, "Senior Data Scientist")]),
  ),
);
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderList(role: "recruiter" | "viewer") {
  server.use(
    http.get("http://localhost:8000/api/auth/me", () =>
      HttpResponse.json({ id: 1, email: "u@acme.com", name: null, picture: null, role }),
    ),
  );
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <JobsList />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("JobsList — New job gating", () => {
  it("offers New job to a recruiter", async () => {
    renderList("recruiter");
    expect(await screen.findByRole("link", { name: /new job/i })).toBeInTheDocument();
  });

  it("hides New job from a viewer", async () => {
    renderList("viewer");
    // Wait for the board to settle so this isn't just an early render.
    await screen.findByText(/senior data scientist/i);
    expect(screen.queryByRole("link", { name: /new job/i })).not.toBeInTheDocument();
  });
});
