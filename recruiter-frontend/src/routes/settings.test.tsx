import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Settings from "./settings";

// Follows the same mocking convention as
// src/components/settings/users-tab.test.tsx: replace the shared `api`
// helper with a hoisted mock rather than standing up MSW handlers for
// every settings endpoint every tab might call.
const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: apiMock };
});

function meResponse(role: "admin" | "recruiter") {
  return { id: 1, email: "u@acme.com", name: "U", picture: null, role };
}

// Only the fields settings.tsx's children actually read are populated;
// the rest exist so useSettings()'s SettingsRead-shaped consumers don't
// choke on missing keys.
const SETTINGS_STUB = {
  default_llm_provider: "anthropic",
  has_anthropic_api_key: false,
  local_llm_url: null,
  has_local_llm_api_key: false,
  model_overrides: {},
  has_google_oauth_tokens: false,
  has_smtp_config: false,
  smtp_host: null,
  smtp_port: null,
  smtp_user: null,
  smtp_from_email: null,
  smtp_use_starttls: null,
  recruiter_name: null,
  recruiter_email: null,
  monthly_llm_spend_cap_usd: null,
  search_provider: null,
  search_engine_id: null,
  has_search_api_key: false,
  has_github_token: false,
  has_apify_api_key: false,
  apify_actor_id: null,
  enrichment_enabled: false,
  has_enrichment_twitter_api_key: false,
  has_enrichment_youtube_api_key: false,
  has_enrichment_stackexchange_key: false,
  enrichment_sources: {},
};

function mockApiForRole(role: "admin" | "recruiter") {
  apiMock.mockReset();
  apiMock.mockImplementation((path: string) => {
    if (path === "/api/auth/me") return Promise.resolve(meResponse(role));
    if (path === "/api/settings") return Promise.resolve(SETTINGS_STUB);
    return Promise.resolve({});
  });
}

function renderSettings() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <Settings />
    </QueryClientProvider>,
  );
}

describe("Settings — role gating", () => {
  it("shows LLM, Sourcing, Notifications, Enrichment, and Users tabs for an admin", async () => {
    mockApiForRole("admin");
    renderSettings();

    // Wait for /api/auth/me to resolve before asserting — isAdmin starts
    // false (me.data undefined) until then.
    expect(await screen.findByRole("tab", { name: "Users" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "LLM" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Sourcing" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Notifications" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Enrichment" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Profile" })).toBeInTheDocument();
  });

  it("hides LLM, Sourcing, Notifications, Enrichment, and Users tabs for a recruiter", async () => {
    mockApiForRole("recruiter");
    renderSettings();

    expect(await screen.findByRole("tab", { name: "Profile" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Users" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "LLM" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Sourcing" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Notifications" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Enrichment" })).not.toBeInTheDocument();
  });

  it("still lets a recruiter reach the change-password form", async () => {
    mockApiForRole("recruiter");
    renderSettings();

    // Profile is the default tab, so its content — including the
    // change-password form, available to every role — is mounted
    // without needing to click anything.
    expect(await screen.findByLabelText("Current password")).toBeInTheDocument();
    expect(screen.getByLabelText("New password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /change password/i })).toBeInTheDocument();
  });
});
