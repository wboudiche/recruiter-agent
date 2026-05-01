import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { useChat } from "./use-chat";

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

const APP_ID = 1;

describe("useChat", () => {
  it("loads history on mount", async () => {
    server.use(
      http.get(`http://localhost:8000/api/applications/${APP_ID}/chat`, () =>
        HttpResponse.json([
          { id: 1, application_id: APP_ID, role: "user", content: "hi",
            tool_calls: null, tool_call_id: null, tool_name: null, tool_result: null,
            created_at: "2026-05-01T00:00:00Z" },
        ]),
      ),
    );

    const { result } = renderHook(() => useChat(APP_ID), { wrapper: wrap() });
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    expect(result.current.messages[0].content).toBe("hi");
  });

  it("streams a turn and appends events to messages", async () => {
    server.use(
      http.get(`http://localhost:8000/api/applications/${APP_ID}/chat`, () =>
        HttpResponse.json([]),
      ),
      http.post(`http://localhost:8000/api/applications/${APP_ID}/chat`, () => {
        const body = [
          { type: "message", role: "user", id: 10, content: "hi" },
          { type: "message_delta", text: "hello back" },
          { type: "message_done", id: 11 },
        ].map((e) => JSON.stringify(e) + "\n").join("");
        return new HttpResponse(body, {
          headers: { "Content-Type": "application/x-ndjson" },
        });
      }),
    );

    const { result } = renderHook(() => useChat(APP_ID), { wrapper: wrap() });
    await waitFor(() => expect(result.current.messages).toEqual([]));

    await act(async () => {
      await result.current.sendMessage("hi");
    });

    expect(result.current.isStreaming).toBe(false);
    const texts = result.current.messages.map((m) => m.content);
    expect(texts).toContain("hi");
    expect(texts).toContain("hello back");
  });

  it("renders an error event into the error state", async () => {
    server.use(
      http.get(`http://localhost:8000/api/applications/${APP_ID}/chat`, () =>
        HttpResponse.json([]),
      ),
      http.post(`http://localhost:8000/api/applications/${APP_ID}/chat`, () => {
        const body = [
          { type: "message", role: "user", id: 1, content: "?" },
          { type: "error", detail: "boom", phase: "llm" },
        ].map((e) => JSON.stringify(e) + "\n").join("");
        return new HttpResponse(body, {
          headers: { "Content-Type": "application/x-ndjson" },
        });
      }),
    );

    const { result } = renderHook(() => useChat(APP_ID), { wrapper: wrap() });
    await waitFor(() => expect(result.current.messages).toEqual([]));
    await act(async () => {
      await result.current.sendMessage("?");
    });
    expect(result.current.error).toBe("boom");
  });
});
