import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { SourcingTab } from "./sourcing-tab";

const server = setupServer();

type Settings = {
  search_provider: string | null;
  search_engine_id: string | null;
  has_search_api_key: boolean;
  has_github_token: boolean;
};

function defaultSettings(overrides: Partial<Settings> = {}): Settings {
  return {
    search_provider: "google_cse",
    search_engine_id: "abcd:1234",
    has_search_api_key: true,
    has_github_token: false,
    ...overrides,
  };
}

function mockSettingsRoutes(initial: Settings, capture: { lastBody?: any }) {
  let current = initial;
  server.use(
    http.get("http://localhost:8000/api/settings", () =>
      HttpResponse.json(current),
    ),
    http.put("http://localhost:8000/api/settings", async ({ request }) => {
      capture.lastBody = await request.json();
      return HttpResponse.json(current);
    }),
  );
}

function renderTab() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <SourcingTab />
      <Toaster />
    </QueryClientProvider>,
  );
}

describe("SourcingTab — multi-provider", () => {
  beforeEach(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => {
    server.resetHandlers();
    server.close();
  });

  it("shows API key + CSE ID for google_cse (default)", async () => {
    const cap: any = {};
    mockSettingsRoutes(defaultSettings(), cap);
    renderTab();
    await waitFor(() => expect(screen.getByLabelText(/CSE ID/i)).toBeInTheDocument());
    expect(screen.getByLabelText(/^API key$/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Instance URL/i)).not.toBeInTheDocument();
  });

  it("switches to Brave: hides CSE ID, keeps API key", async () => {
    const cap: any = {};
    mockSettingsRoutes(defaultSettings(), cap);
    renderTab();
    await waitFor(() => expect(screen.getByLabelText(/CSE ID/i)).toBeInTheDocument());

    await userEvent.click(screen.getByRole("combobox", { name: /provider/i }));
    await userEvent.click(screen.getByRole("option", { name: /brave search/i }));

    expect(screen.getByLabelText(/^API key$/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/CSE ID/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Instance URL/i)).not.toBeInTheDocument();
  });

  it("switches to SearXNG: shows Instance URL, hides API key + CSE ID", async () => {
    const cap: any = {};
    mockSettingsRoutes(defaultSettings(), cap);
    renderTab();
    await waitFor(() => expect(screen.getByLabelText(/CSE ID/i)).toBeInTheDocument());

    await userEvent.click(screen.getByRole("combobox", { name: /provider/i }));
    await userEvent.click(screen.getByRole("option", { name: /searxng/i }));

    expect(screen.getByLabelText(/Instance URL/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^API key$/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/CSE ID/i)).not.toBeInTheDocument();
  });

  it("switches to SerpAPI: shows API key, hides CSE ID + Instance URL", async () => {
    const cap: any = {};
    mockSettingsRoutes(defaultSettings(), cap);
    renderTab();
    await waitFor(() => expect(screen.getByLabelText(/CSE ID/i)).toBeInTheDocument());

    await userEvent.click(screen.getByRole("combobox", { name: /provider/i }));
    await userEvent.click(screen.getByRole("option", { name: /serpapi/i }));

    expect(screen.getByLabelText(/^API key$/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/CSE ID/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Instance URL/i)).not.toBeInTheDocument();
  });

  it("save while SerpAPI is selected sends only search_provider + search_api_key", async () => {
    const cap: any = {};
    mockSettingsRoutes(defaultSettings(), cap);
    renderTab();
    await waitFor(() => expect(screen.getByLabelText(/CSE ID/i)).toBeInTheDocument());

    await userEvent.click(screen.getByRole("combobox", { name: /provider/i }));
    await userEvent.click(screen.getByRole("option", { name: /serpapi/i }));
    await userEvent.type(screen.getByLabelText(/^API key$/i), "serp_xyz");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(cap.lastBody).toBeDefined());
    expect(cap.lastBody.search_provider).toBe("serpapi");
    expect(cap.lastBody.search_api_key).toBe("serp_xyz");
    expect(cap.lastBody).not.toHaveProperty("search_engine_id");
  });

  it("save while Brave is selected sends only search_provider + search_api_key", async () => {
    const cap: any = {};
    mockSettingsRoutes(defaultSettings(), cap);
    renderTab();
    await waitFor(() => expect(screen.getByLabelText(/CSE ID/i)).toBeInTheDocument());

    await userEvent.click(screen.getByRole("combobox", { name: /provider/i }));
    await userEvent.click(screen.getByRole("option", { name: /brave search/i }));
    await userEvent.type(screen.getByLabelText(/^API key$/i), "brv_xyz");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(cap.lastBody).toBeDefined());
    expect(cap.lastBody.search_provider).toBe("brave");
    expect(cap.lastBody.search_api_key).toBe("brv_xyz");
    expect(cap.lastBody).not.toHaveProperty("search_engine_id");
  });

  it("save while SearXNG is selected sends only search_provider + search_engine_id", async () => {
    const cap: any = {};
    mockSettingsRoutes(defaultSettings(), cap);
    renderTab();
    await waitFor(() => expect(screen.getByLabelText(/CSE ID/i)).toBeInTheDocument());

    await userEvent.click(screen.getByRole("combobox", { name: /provider/i }));
    await userEvent.click(screen.getByRole("option", { name: /searxng/i }));
    await userEvent.clear(screen.getByLabelText(/Instance URL/i));
    await userEvent.type(screen.getByLabelText(/Instance URL/i), "http://localhost:8080");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(cap.lastBody).toBeDefined());
    expect(cap.lastBody.search_provider).toBe("searxng");
    expect(cap.lastBody.search_engine_id).toBe("http://localhost:8080");
    expect(cap.lastBody).not.toHaveProperty("search_api_key");
  });

  it("typing in API key under Brave then switching to SearXNG drops the key from the save", async () => {
    const cap: any = {};
    mockSettingsRoutes(defaultSettings(), cap);
    renderTab();
    await waitFor(() => expect(screen.getByLabelText(/CSE ID/i)).toBeInTheDocument());

    // Switch to Brave, type a key.
    await userEvent.click(screen.getByRole("combobox", { name: /provider/i }));
    await userEvent.click(screen.getByRole("option", { name: /brave search/i }));
    await userEvent.type(screen.getByLabelText(/^API key$/i), "brv_should_not_persist");

    // Switch to SearXNG and save.
    await userEvent.click(screen.getByRole("combobox", { name: /provider/i }));
    await userEvent.click(screen.getByRole("option", { name: /searxng/i }));
    await userEvent.type(screen.getByLabelText(/Instance URL/i), "http://localhost:8080");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(cap.lastBody).toBeDefined());
    expect(cap.lastBody).not.toHaveProperty("search_api_key");
  });
});
