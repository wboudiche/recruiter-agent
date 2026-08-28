import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { AddCandidatePanel } from "./add-candidate-panel";

function wrap() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

// The panel exists solely to create candidates — a viewer must never see
// a live form here regardless of how `open` got set to true.
describe("AddCandidatePanel", () => {
  it("shows a read-only notice and no form when canWrite is false", () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <AddCandidatePanel jobId={1} open onOpenChange={() => {}} canWrite={false} />
      </Wrapper>,
    );
    expect(screen.getByText(/read-only access/i)).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /url/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add candidate/i })).not.toBeInTheDocument();
  });

  it("shows the add-candidate form when canWrite is true", () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <AddCandidatePanel jobId={1} open onOpenChange={() => {}} canWrite />
      </Wrapper>,
    );
    expect(screen.getByRole("tab", { name: /url/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add candidate/i })).toBeInTheDocument();
    expect(screen.queryByText(/read-only access/i)).not.toBeInTheDocument();
  });
});
