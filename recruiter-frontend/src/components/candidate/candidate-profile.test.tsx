import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CandidateProfile } from "./candidate-profile";
import type { CandidateRead } from "@/hooks/use-candidate";

function candidate(overrides: Partial<CandidateRead> = {}): CandidateRead {
  return {
    id: 1, full_name: "Alice Example", email: "alice@example.com",
    phone: null, location: null, headline: null, summary: null,
    skills: [], experience: [], education: [], links: [],
    source_type: null, source_url: null, resume_path: null, photo_url: null,
    created_at: "2026-05-05T00:00:00Z", updated_at: "2026-05-05T00:00:00Z",
    ...overrides,
  };
}

function renderProfile(canWrite?: boolean) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <CandidateProfile candidate={candidate()} canWrite={canWrite} />
    </QueryClientProvider>,
  );
}

// PATCHes /api/candidates/{id} — a write. These edit affordances are not
// gated by the server-side allowlist the way chat is, so a viewer who
// clicks them gets a 403.
describe("CandidateProfile — edit affordances", () => {
  it("offers Edit photo and Edit profile details to a recruiter", () => {
    renderProfile(true);
    expect(screen.getByRole("button", { name: /edit photo/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /edit profile details/i })).toBeInTheDocument();
  });

  it("hides Edit photo and Edit profile details from a viewer", () => {
    renderProfile(false);
    expect(screen.queryByRole("button", { name: /edit photo/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /edit profile details/i })).not.toBeInTheDocument();
  });
});
