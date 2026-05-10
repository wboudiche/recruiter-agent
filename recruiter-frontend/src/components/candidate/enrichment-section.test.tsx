import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { EnrichmentSection } from "./enrichment-section";

function bundle(overrides = {}) {
  return {
    fetched_at: "2026-04-30T12:00:00Z",
    expires_at: "2026-05-30T12:00:00Z",
    discovery_consent: true,
    results: [
      {
        source: "github",
        confidence: 1.0,
        discovered: false,
        profile_url: "https://github.com/alice",
        signals: [
          {
            type: "code",
            summary: "rust-helper [Rust, 120 stars]",
            url: "https://github.com/alice/rust-helper",
          },
        ],
        summary: "GitHub @alice: 42 repos.",
      },
      {
        source: "mastodon",
        confidence: 0.5,
        discovered: true,
        profile_url: "https://mastodon.social/@alice",
        signals: [
          {
            type: "post",
            summary: "@alice@mastodon.social: Just shipped …",
          },
        ],
        summary: "Mastodon @alice@mastodon.social.",
      },
    ],
    errors: [],
    ...overrides,
  };
}

function renderSection(props: { applicationId: number; enrichment: unknown }) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <EnrichmentSection
        applicationId={props.applicationId}
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        enrichment={props.enrichment as any}
      />
      <Toaster />
    </QueryClientProvider>,
  );
}

describe("EnrichmentSection", () => {
  it("renders high-confidence findings prominently", () => {
    renderSection({ applicationId: 1, enrichment: bundle() });
    expect(screen.getByText(/GitHub @alice/i)).toBeInTheDocument();
  });

  it("collapses low-confidence findings under a toggle", async () => {
    renderSection({ applicationId: 1, enrichment: bundle() });
    expect(screen.queryByText(/Mastodon @alice/i)).not.toBeVisible();
    await userEvent.click(
      screen.getByRole("button", { name: /unconfirmed match/i }),
    );
    expect(screen.getByText(/Mastodon @alice/i)).toBeVisible();
  });

  it("shows discovered badge for low-confidence sources", async () => {
    renderSection({ applicationId: 1, enrichment: bundle() });
    await userEvent.click(
      screen.getByRole("button", { name: /unconfirmed match/i }),
    );
    expect(screen.getByText(/Discovered/i)).toBeInTheDocument();
  });

  it("renders cached/expires hint", () => {
    renderSection({ applicationId: 1, enrichment: bundle() });
    expect(screen.getByText(/expires/i)).toBeInTheDocument();
  });

  it("re-enrich button calls the API and refetches", async () => {
    const server = setupServer(
      http.post("http://localhost:8000/api/applications/1/re-enrich", () =>
        HttpResponse.json({ application_id: 1 }, { status: 202 }),
      ),
      http.get("http://localhost:8000/api/applications/1", () =>
        HttpResponse.json({ id: 1, enrichment: bundle() }),
      ),
    );
    server.listen();
    try {
      renderSection({ applicationId: 1, enrichment: bundle() });
      await userEvent.click(
        screen.getByRole("button", { name: /re-enrich/i }),
      );
      await waitFor(() =>
        expect(screen.getByText(/queued/i)).toBeInTheDocument(),
      );
    } finally {
      server.close();
    }
  });

  it("renders per-source errors when present", () => {
    renderSection({
      applicationId: 1,
      enrichment: bundle({
        errors: [{ source: "twitter", error: "401", transient: false }],
      }),
    });
    expect(screen.getByText(/twitter/i)).toBeInTheDocument();
    expect(screen.getByText(/401/i)).toBeInTheDocument();
  });

  it("renders nothing when enrichment is null", () => {
    const { container } = renderSection({
      applicationId: 1,
      enrichment: null,
    });
    expect(container.textContent).toBe("");
  });
});
