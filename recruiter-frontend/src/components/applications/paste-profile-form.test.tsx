import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { PasteProfileForm } from "./paste-profile-form";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function wrap() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("PasteProfileForm", () => {
  it("submits content to the paste endpoint", async () => {
    let received: unknown;
    server.use(
      http.post(
        "http://localhost:8000/api/applications/42/paste",
        async ({ request }) => {
          received = await request.json();
          return HttpResponse.json({ application_id: 42 }, { status: 202 });
        },
      ),
    );
    const Wrapper = wrap();
    render(
      <Wrapper>
        <PasteProfileForm applicationId={42} sourceUrl={null} />
      </Wrapper>,
    );
    const ta = screen.getByPlaceholderText(/paste the candidate/i);
    fireEvent.change(ta, { target: { value: "Alice profile content" } });
    fireEvent.click(screen.getByRole("button", { name: /submit/i }));
    // Wait for mutation: the textarea should clear on success
    await waitFor(() => {
      expect((ta as HTMLTextAreaElement).value).toBe("");
    });
    expect(received).toEqual({ content: "Alice profile content" });
  });

  it("submit is disabled until content is non-empty", () => {
    const Wrapper = wrap();
    render(
      <Wrapper>
        <PasteProfileForm applicationId={42} />
      </Wrapper>,
    );
    expect(screen.getByRole("button", { name: /submit/i })).toBeDisabled();
  });
});
