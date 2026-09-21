import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// No artificial inter-event delay: these tests only click tabs, and the
// default delay makes four full-route mounts slow enough to starve other
// files running in parallel.
const user = () => userEvent.setup({ delay: null });
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import ApplicationDetail from "./application-detail";

const server = setupServer(
  http.get("http://localhost:8000/api/auth/me", () =>
    HttpResponse.json({ id: 1, email: "a@b.c", role: "admin" }),
  ),
  http.get("http://localhost:8000/api/applications/1", () =>
    HttpResponse.json({
      id: 1, job_id: 6, candidate_id: 9, stage: "scheduled",
      score: 68, score_breakdown: [], score_rationale: null,
      enrichment: null, awaiting_paste: false, rejection_reason: null,
    }),
  ),
  http.get("http://localhost:8000/api/candidates/9", () =>
    HttpResponse.json({
      id: 9, full_name: "Slim Boughenia", headline: "SRE",
      summary: "A distinctive summary line", skills: [], experience: [], education: [],
    }),
  ),
  http.get("http://localhost:8000/api/jobs/6", () =>
    HttpResponse.json({ id: 6, title: "Senior DevOps", criteria: [] }),
  ),
  http.get("http://localhost:8000/api/interview-templates", () => HttpResponse.json([])),
  http.get("http://localhost:8000/api/applications/1/interview-kit", () =>
    HttpResponse.json({
      kit: {
        status: "ready",
        questions: [{
          id: "p1", text: "Describe a production Kubernetes outage you owned.",
          source: "probe", criterion: "Kubernetes", answer: null, rating: null,
        }],
      },
    }),
  ),
  http.get("http://localhost:8000/api/applications/1/chat", () => HttpResponse.json([])),
);
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function mount(initialEntry = "/applications/1") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/applications/:appId" element={<ApplicationDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ApplicationDetail tabs", () => {
  it("opens on Profile, with the interview kit not rendered at all", async () => {
    mount();
    await waitFor(() =>
      expect(screen.getByText("A distinctive summary line")).toBeInTheDocument(),
    );

    // Not merely hidden — absent, so its query never fires on a profile view.
    expect(
      screen.queryByDisplayValue("Describe a production Kubernetes outage you owned."),
    ).not.toBeInTheDocument();
  });

  it("switches to the interview kit and back", async () => {
    const u = user();
    mount();
    await waitFor(() =>
      expect(screen.getByText("A distinctive summary line")).toBeInTheDocument(),
    );

    await u.click(screen.getByRole("tab", { name: /interview kit/i }));
    await waitFor(() =>
      expect(
        screen.getByDisplayValue("Describe a production Kubernetes outage you owned."),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("A distinctive summary line")).not.toBeInTheDocument();
    // Stage and its actions stay visible on the kit tab: marking someone
    // interviewed must not require navigating back to Profile.
    expect(screen.getByText(/scheduled/i)).toBeInTheDocument();

    await u.click(screen.getByRole("tab", { name: /profile/i }));
    await waitFor(() =>
      expect(screen.getByText("A distinctive summary line")).toBeInTheDocument(),
    );
  });

  it("opens straight onto the kit when the URL asks for it", async () => {
    // So a refresh mid-interview does not dump you back on Profile, and the
    // tab can be bookmarked or opened in a second window beside the call.
    mount("/applications/1?tab=interview");
    await waitFor(() =>
      expect(
        screen.getByDisplayValue("Describe a production Kubernetes outage you owned."),
      ).toBeInTheDocument(),
    );
  });
});
