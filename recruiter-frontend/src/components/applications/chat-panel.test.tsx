import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { ChatPanel } from "./chat-panel";

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

describe("ChatPanel", () => {
  it("shows empty state with no history", async () => {
    server.use(
      http.get("http://localhost:8000/api/applications/1/chat", () =>
        HttpResponse.json([]),
      ),
    );
    render(<ChatPanel applicationId={1} />, { wrapper: wrap() });
    await waitFor(() =>
      expect(screen.getByText(/ask anything/i)).toBeInTheDocument(),
    );
  });

  it("renders a user message and an assistant message", async () => {
    server.use(
      http.get("http://localhost:8000/api/applications/1/chat", () =>
        HttpResponse.json([
          { id: 1, application_id: 1, role: "user", content: "hi",
            tool_calls: null, tool_call_id: null, tool_name: null, tool_result: null,
            created_at: "2026-05-01T00:00:00Z" },
          { id: 2, application_id: 1, role: "assistant", content: "hello",
            tool_calls: null, tool_call_id: null, tool_name: null, tool_result: null,
            created_at: "2026-05-01T00:00:01Z" },
        ]),
      ),
    );
    render(<ChatPanel applicationId={1} />, { wrapper: wrap() });
    await waitFor(() => expect(screen.getByText("hi")).toBeInTheDocument());
    expect(screen.getByText("hello")).toBeInTheDocument();
  });

  it("renders a tool-call card collapsed by default and expands on click", async () => {
    server.use(
      http.get("http://localhost:8000/api/applications/1/chat", () =>
        HttpResponse.json([
          { id: 1, application_id: 1, role: "tool", content: null, tool_calls: null,
            tool_call_id: "tc1", tool_name: "get_candidate",
            tool_result: { full_name: "Marie" },
            created_at: "2026-05-01T00:00:00Z" },
        ]),
      ),
    );
    render(<ChatPanel applicationId={1} />, { wrapper: wrap() });
    await waitFor(() => expect(screen.getByText(/get_candidate/)).toBeInTheDocument());
    expect(screen.queryByText(/Marie/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByText(/get_candidate/));
    expect(screen.getByText(/Marie/)).toBeInTheDocument();
  });

  it("renders an Undo button on validate/reject tool results and triggers undo", async () => {
    let undoCalls = 0;
    server.use(
      http.get("http://localhost:8000/api/applications/1/chat", () =>
        HttpResponse.json([
          { id: 1, application_id: 1, role: "tool", content: null, tool_calls: null,
            tool_call_id: "tc1", tool_name: "validate_application",
            tool_result: { ok: true, previous_stage: "scored", undo_token: "tok-123" },
            created_at: "2026-05-01T00:00:00Z" },
        ]),
      ),
      http.post("http://localhost:8000/api/applications/1/undo", () => {
        undoCalls++;
        return HttpResponse.json({
          id: 1, job_id: 1, candidate_id: 1, stage: "scored", score: 80,
          score_breakdown: null, score_rationale: null, notes: null,
          validated_at: null, invited_at: null, scheduled_at: null, rejected_at: null,
          created_at: "2026-05-01T00:00:00Z", updated_at: "2026-05-01T00:00:01Z",
        });
      }),
    );
    render(<ChatPanel applicationId={1} />, { wrapper: wrap() });
    const button = await screen.findByRole("button", { name: /undo/i });
    await userEvent.click(button);
    await waitFor(() => expect(undoCalls).toBe(1));
  });
});
