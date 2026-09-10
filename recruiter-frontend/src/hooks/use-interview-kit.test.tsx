import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { useInterviewKit } from "./use-interview-kit";

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
});
