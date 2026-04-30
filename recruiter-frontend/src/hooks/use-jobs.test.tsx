import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactNode } from "react";
import { useJobs } from "./use-jobs";

const server = setupServer();

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const sampleJob = {
  id: 1,
  title: "Backend Engineer",
  description: "Build APIs",
  criteria: [],
  status: "open",
  created_at: "2026-04-30T08:00:00Z",
  updated_at: "2026-04-30T08:00:00Z",
};

describe("useJobs", () => {
  beforeEach(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => {
    server.resetHandlers();
    server.close();
  });

  it("returns the list of jobs", async () => {
    server.use(
      http.get("http://localhost:8000/api/jobs", () =>
        HttpResponse.json([sampleJob]),
      ),
    );
    const { result } = renderHook(() => useJobs(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([sampleJob]);
  });

  it("surfaces errors", async () => {
    server.use(
      http.get("http://localhost:8000/api/jobs", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    const { result } = renderHook(() => useJobs(), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
