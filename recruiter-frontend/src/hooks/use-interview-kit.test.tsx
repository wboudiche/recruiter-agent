import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { useInterviewKit } from "./use-interview-kit";
import { queryKeys } from "@/lib/query-keys";

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

describe("useInterviewKit", () => {
  it("loads the kit", async () => {
    server.use(
      http.get("http://localhost:8000/api/applications/1/interview-kit", () =>
        HttpResponse.json({ kit: { status: "ready", questions: [
          { id: "q1", text: "Q?", source: "probe", answer: null, rating: null },
        ] } }),
      ),
    );
    const { result } = renderHook(() => useInterviewKit(1), { wrapper: wrap() });
    await waitFor(() => expect(result.current.kit?.questions).toHaveLength(1));
    expect(result.current.kit?.status).toBe("ready");
  });

  it("reports a null kit as absent rather than erroring", async () => {
    server.use(
      http.get("http://localhost:8000/api/applications/1/interview-kit", () =>
        HttpResponse.json({ kit: null }),
      ),
    );
    const { result } = renderHook(() => useInterviewKit(1), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.kit).toBeNull();
  });

  it("exposes isError distinctly from an absent kit when the request fails", async () => {
    server.use(
      http.get("http://localhost:8000/api/applications/1/interview-kit", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    const { result } = renderHook(() => useInterviewKit(1), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.kit).toBeNull();
  });

  it("invalidates both interview-kit and application queries on submit", async () => {
    server.use(
      http.post("http://localhost:8000/api/applications/1/interview-kit/submit", () =>
        HttpResponse.json({ status: "submitted", questions: [] }),
      ),
    );
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const invalidateSpy = vi.spyOn(qc, "invalidateQueries");
    const { result } = renderHook(() => useInterviewKit(1), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
      ),
    });
    result.current.submit.mutate();
    await waitFor(() => expect(invalidateSpy).toHaveBeenCalled());
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.interviewKit(1),
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.application(1),
    });
  });
});
