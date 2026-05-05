import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { SearchResultCard } from "./search-result-card";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function wrap() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

const RESULT = {
  name: "Alice Doe",
  url: "https://www.linkedin.com/in/alice/",
  snippet: "5 years Rust",
  source: "linkedin" as const,
};

describe("SearchResultCard", () => {
  it("renders name, source, snippet, and url", () => {
    const Wrapper = wrap();
    render(<Wrapper><SearchResultCard result={RESULT} jobId={1} /></Wrapper>);
    expect(screen.getByText("Alice Doe")).toBeInTheDocument();
    expect(screen.getByText(/5 years Rust/i)).toBeInTheDocument();
    // The URL link is present and points at the result.url.
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", RESULT.url);
  });

  it("Add button POSTs to /api/jobs/{id}/candidates", async () => {
    let received: unknown;
    server.use(
      http.post("http://localhost:8000/api/jobs/1/candidates", async ({ request }) => {
        received = await request.json();
        return HttpResponse.json({ application_id: 99 }, { status: 202 });
      }),
    );
    const Wrapper = wrap();
    render(<Wrapper><SearchResultCard result={RESULT} jobId={1} /></Wrapper>);
    fireEvent.click(screen.getByRole("button", { name: /add/i }));
    await waitFor(() => expect(received).toEqual({ kind: "url", url: RESULT.url }));
  });
});

describe("SearchResultCard — added state", () => {
  it("button shows 'Added ✓' and stays disabled after a successful Add", async () => {
    server.use(
      http.post("http://localhost:8000/api/jobs/1/candidates", () =>
        HttpResponse.json({ application_id: 99 }, { status: 202 }),
      ),
    );
    const Wrapper = wrap();
    render(<Wrapper><SearchResultCard result={RESULT} jobId={1} /></Wrapper>);
    const btn = screen.getByRole("button", { name: /add/i });
    fireEvent.click(btn);
    await waitFor(() => {
      const after = screen.getByRole("button", { name: /added/i });
      expect(after).toBeDisabled();
      expect(after.textContent).toMatch(/added/i);
    });
  });
});
