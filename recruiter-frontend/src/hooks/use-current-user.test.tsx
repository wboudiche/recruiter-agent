import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { useCurrentUser } from "./use-current-user";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("useCurrentUser", () => {
  it("returns user payload on 200", async () => {
    server.use(
      http.get("http://localhost:8000/api/auth/me", () =>
        HttpResponse.json({ id: 1, email: "alice@acme.com", name: "Alice", picture: null }),
      ),
    );
    const { result } = renderHook(() => useCurrentUser(), { wrapper: wrap() });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data?.email).toBe("alice@acme.com");
  });

  it("does not retry on 401 (no infinite loop)", async () => {
    let calls = 0;
    server.use(
      http.get("http://localhost:8000/api/auth/me", () => {
        calls++;
        return new HttpResponse("unauth", { status: 401 });
      }),
    );
    const { result } = renderHook(() => useCurrentUser(), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isFetching).toBe(false), { timeout: 1000 });
    expect(calls).toBe(1);
  });
});
