import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { EnrichmentTab } from "./enrichment-tab";

const server = setupServer();

const SOURCE_LABELS: Record<string, string> = {
  github: "GitHub",
  stackoverflow: "Stack Overflow",
  hackernews: "Hacker News",
  reddit: "Reddit",
  mastodon: "Mastodon",
  bluesky: "Bluesky",
  youtube: "YouTube",
  twitter: "Twitter / X",
  devto: "Dev.to",
  blog: "Blog / website (LLM summary)",
};

function defaults(overrides = {}) {
  return {
    enrichment_enabled: false,
    has_enrichment_twitter_api_key: false,
    has_enrichment_youtube_api_key: false,
    has_enrichment_stackexchange_key: false,
    enrichment_sources: {},
    default_llm_provider: "anthropic", has_anthropic_api_key: false,
    local_llm_url: null, has_local_llm_api_key: false, model_overrides: {},
    has_google_oauth_tokens: false, has_smtp_config: false,
    recruiter_name: null, recruiter_email: null, monthly_llm_spend_cap_usd: null,
    search_provider: null, search_engine_id: null, has_search_api_key: false,
    has_github_token: false,
    ...overrides,
  };
}

function mockRoutes(initial: ReturnType<typeof defaults>, capture: { lastBody?: any }) {
  const cur = initial;
  server.use(
    http.get("http://localhost:8000/api/settings", () => HttpResponse.json(cur)),
    http.put("http://localhost:8000/api/settings", async ({ request }) => {
      capture.lastBody = await request.json();
      return HttpResponse.json(cur);
    }),
  );
}

function renderTab() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <EnrichmentTab />
      <Toaster />
    </QueryClientProvider>,
  );
}

describe("EnrichmentTab", () => {
  beforeEach(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => { server.resetHandlers(); server.close(); });

  it("renders master toggle and 10 source checkboxes", async () => {
    const cap: { lastBody?: any } = {};
    mockRoutes(defaults(), cap);
    renderTab();
    await waitFor(() => expect(screen.getByLabelText(/Enable enrichment/i)).toBeInTheDocument());
    for (const label of Object.values(SOURCE_LABELS)) {
      expect(screen.getByLabelText(label, { exact: true })).toBeInTheDocument();
    }
  });

  it("shows masked placeholder for keys when set on the server", async () => {
    const cap: { lastBody?: any } = {};
    mockRoutes(defaults({ has_enrichment_twitter_api_key: true }), cap);
    renderTab();
    const twKey = await screen.findByLabelText(/Twitter.*API key/i);
    expect(twKey).toHaveAttribute("placeholder", expect.stringContaining("(set)"));
  });

  it("toggling a source sends the new map on save", async () => {
    const cap: { lastBody?: any } = {};
    mockRoutes(defaults({ enrichment_enabled: true }), cap);
    renderTab();
    const twitter = await screen.findByLabelText(SOURCE_LABELS.twitter, { exact: true });
    await userEvent.click(twitter);  // off
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(cap.lastBody).toBeDefined());
    expect(cap.lastBody.enrichment_sources.twitter).toBe(false);
  });

  it("typing a Twitter key sends it through on save", async () => {
    const cap: { lastBody?: any } = {};
    mockRoutes(defaults({ enrichment_enabled: true }), cap);
    renderTab();
    const tk = await screen.findByLabelText(/Twitter.*API key/i);
    await userEvent.type(tk, "tk-abc");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(cap.lastBody).toBeDefined());
    expect(cap.lastBody.enrichment_twitter_api_key).toBe("tk-abc");
  });

  it("enabling the master toggle sends enrichment_enabled=true", async () => {
    const cap: { lastBody?: any } = {};
    mockRoutes(defaults(), cap);
    renderTab();
    const toggle = await screen.findByLabelText(/Enable enrichment/i);
    await userEvent.click(toggle);
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(cap.lastBody).toBeDefined());
    expect(cap.lastBody.enrichment_enabled).toBe(true);
  });
});
