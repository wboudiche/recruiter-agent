import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { EditCriteriaSheet } from "./edit-criteria-sheet";
import type { JobRead } from "@/hooks/use-jobs";

function job(): JobRead {
  return {
    id: 1, title: "Backend Engineer", description: "D", status: "open",
    created_at: "2026-05-05T00:00:00Z", updated_at: "2026-05-05T00:00:00Z",
    criteria: [{ name: "Rust", weight: 0.5, description: "" }],
  };
}

function wrap() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("EditCriteriaSheet — viewer read-only", () => {
  it("disables the weight input (not just readOnly) so its spinner/scroll stepper can't change the value", () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <EditCriteriaSheet job={job()} open onOpenChange={() => {}} canWrite={false} />
      </Wrapper>,
    );
    const weight = screen.getByLabelText(/weight/i);
    expect(weight).toBeDisabled();
  });

  it("leaves the weight input enabled for a recruiter", () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <EditCriteriaSheet job={job()} open onOpenChange={() => {}} canWrite />
      </Wrapper>,
    );
    const weight = screen.getByLabelText(/weight/i);
    expect(weight).not.toBeDisabled();
  });
});
