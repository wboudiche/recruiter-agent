import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { LlmTab } from "./llm-tab";

const server = setupServer();

function defaultSettings(overrides: Record<string, unknown> = {}) {
  return {
    default_llm_provider: "anthropic",
    has_anthropic_api_key: true,
    local_llm_url: "http://localhost:11434/v1",
    has_local_llm_api_key: true,
    model_overrides: {},
    ...overrides,
  };
}

function mockSettingsRoutes(initial: Record<string, unknown>, capture: { lastBody?: any }) {
  server.use(
    http.get("http://localhost:8000/api/settings", () => HttpResponse.json(initial)),
    http.put("http://localhost:8000/api/settings", async ({ request }) => {
      capture.lastBody = await request.json();
      return HttpResponse.json(initial);
    }),
  );
}

function renderTab() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return render(<Wrapper><LlmTab /></Wrapper>);
}

describe("LlmTab secret fields", () => {
  beforeEach(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => {
    server.resetHandlers();
    server.close();
  });

  it("Clear on the Anthropic key sends an explicit empty string", async () => {
    const cap: any = {};
    mockSettingsRoutes(defaultSettings(), cap);
    renderTab();
    await waitFor(() =>
      expect(screen.getByLabelText(/^Anthropic API key$/i)).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByRole("button", { name: /clear anthropic api key/i }));
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(cap.lastBody).toBeDefined());
    expect(cap.lastBody.anthropic_api_key).toBe("");
  });

  it("an unrelated save leaves the stored keys alone", async () => {
    const cap: any = {};
    mockSettingsRoutes(defaultSettings(), cap);
    renderTab();
    await waitFor(() =>
      expect(screen.getByLabelText(/^Anthropic API key$/i)).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(cap.lastBody).toBeDefined());
    expect(cap.lastBody).not.toHaveProperty("anthropic_api_key");
    expect(cap.lastBody).not.toHaveProperty("local_llm_api_key");
  });

  it("switching provider drops a pending Clear on the field it hides", async () => {
    // Otherwise the warning unmounts with the field and the revoke is still
    // sent on save — deleting a credential with nothing on screen to say so.
    const cap: any = {};
    mockSettingsRoutes(defaultSettings(), cap);
    renderTab();
    await waitFor(() =>
      expect(screen.getByLabelText(/^Anthropic API key$/i)).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByRole("button", { name: /clear anthropic api key/i }));
    await userEvent.click(screen.getByRole("combobox", { name: /provider/i }));
    await userEvent.click(screen.getByRole("option", { name: /local/i }));
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(cap.lastBody).toBeDefined());
    expect(cap.lastBody).not.toHaveProperty("anthropic_api_key");
  });

  it("switching provider drops a pending Clear on the local key too", async () => {
    const cap: any = {};
    mockSettingsRoutes(defaultSettings({ default_llm_provider: "local" }), cap);
    renderTab();
    await waitFor(() =>
      expect(screen.getByLabelText(/^Local LLM API key \(optional\)$/i)).toBeInTheDocument(),
    );

    await userEvent.click(
      screen.getByRole("button", { name: /clear local llm api key/i }),
    );
    await userEvent.click(screen.getByRole("combobox", { name: /provider/i }));
    await userEvent.click(screen.getByRole("option", { name: /anthropic/i }));
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(cap.lastBody).toBeDefined());
    expect(cap.lastBody).not.toHaveProperty("local_llm_api_key");
  });
});
