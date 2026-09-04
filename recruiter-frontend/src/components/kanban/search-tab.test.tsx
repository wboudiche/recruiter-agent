import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, fireEvent } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { SearchTab } from "./search-tab";

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

describe("SearchTab", () => {
  it("Search button is disabled until ≥1 source AND non-empty query", () => {
    const Wrapper = wrap();
    render(<Wrapper><SearchTab jobId={1} /></Wrapper>);
    const search = screen.getByRole("button", { name: /^search$/i });
    expect(search).toBeDisabled();

    // Pick a source.
    fireEvent.click(screen.getByRole("button", { name: /^github$/i }));
    expect(search).toBeDisabled();  // still no query

    // Type a query.
    fireEvent.change(screen.getByPlaceholderText(/senior rust/i), {
      target: { value: "rust" },
    });
    expect(search).not.toBeDisabled();
  });

  it("submits the right body and renders result cards", async () => {
    let received: unknown;
    server.use(
      http.post("http://localhost:8000/api/sourcing/search", async ({ request }) => {
        received = await request.json();
        return HttpResponse.json({
          results: [{
            name: "Alice", url: "https://github.com/alice",
            snippet: "Rust dev", source: "github",
          }],
          errors: [],
        });
      }),
    );
    const Wrapper = wrap();
    render(<Wrapper><SearchTab jobId={1} /></Wrapper>);
    fireEvent.click(screen.getByRole("button", { name: /^github$/i }));
    fireEvent.change(screen.getByPlaceholderText(/senior rust/i), {
      target: { value: "rust" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));

    await screen.findByText("Alice");
    expect(received).toEqual({
      sources: ["github"], query: "rust", limit_per_source: 5,
    });
  });

  it("renders an error banner when the response has errors", async () => {
    server.use(
      http.post("http://localhost:8000/api/sourcing/search", () =>
        HttpResponse.json({
          results: [],
          errors: [{ source: "linkedin", reason: "not configured", transient: false }],
        }),
      ),
    );
    const Wrapper = wrap();
    render(<Wrapper><SearchTab jobId={1} /></Wrapper>);
    fireEvent.click(screen.getByRole("button", { name: /^linkedin$/i }));
    fireEvent.change(screen.getByPlaceholderText(/senior rust/i), {
      target: { value: "rust" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));

    await screen.findByText(/linkedin/i);
    expect(screen.getByText(/not configured/i)).toBeInTheDocument();
  });

  it("gives the error banner a readable text colour", async () => {
    // bg-yellow-50 is near-white; with no text colour the copy inherits the
    // theme's cream foreground and lands at ~1.05:1 contrast — invisible.
    server.use(
      http.post("http://localhost:8000/api/sourcing/search", () =>
        HttpResponse.json({
          results: [],
          errors: [{ source: "linkedin", reason: "every engine blocked", transient: true }],
        }),
      ),
    );
    const Wrapper = wrap();
    render(<Wrapper><SearchTab jobId={1} /></Wrapper>);
    fireEvent.click(screen.getByRole("button", { name: /^linkedin$/i }));
    fireEvent.change(screen.getByPlaceholderText(/senior rust/i), {
      target: { value: "rust" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));

    const banner = (await screen.findByText(/every engine blocked/i)).closest("div")!;
    expect(banner.className).toMatch(/bg-yellow-50/);
    expect(banner.className).toMatch(/text-yellow-\d{3}/);
  });

  it("renders 'No results found' empty state when both arrays are empty", async () => {
    server.use(
      http.post("http://localhost:8000/api/sourcing/search", () =>
        HttpResponse.json({ results: [], errors: [] }),
      ),
    );
    const Wrapper = wrap();
    render(<Wrapper><SearchTab jobId={1} /></Wrapper>);
    fireEvent.click(screen.getByRole("button", { name: /^web$/i }));
    fireEvent.change(screen.getByPlaceholderText(/senior rust/i), {
      target: { value: "zzznoresults" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));

    await screen.findByText(/no results found/i);
  });
});
