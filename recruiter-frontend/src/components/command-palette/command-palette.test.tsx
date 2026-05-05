import { describe, it, afterEach, beforeAll, afterAll } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { render, screen, fireEvent } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { CommandPaletteProvider, useCommandPalette } from "./command-palette-context";
import { CommandPalette } from "./command-palette";
import { ThemeProvider } from "@/components/theme/theme-provider";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  localStorage.clear();
});
afterAll(() => server.close());

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <MemoryRouter>
          <CommandPaletteProvider>{children}</CommandPaletteProvider>
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

function Opener() {
  const ctx = useCommandPalette();
  return <button onClick={() => ctx.setOpen(true)}>open palette</button>;
}

describe("CommandPalette", () => {
  it("opens via the context setter and lists jobs", async () => {
    server.use(
      http.get("http://localhost:8000/api/jobs", () =>
        HttpResponse.json([
          { id: 1, title: "Backend", description: "x", criteria: [], status: "open",
            created_at: "2026-05-05T00:00:00Z", updated_at: "2026-05-05T00:00:00Z" },
        ]),
      ),
    );
    const Wrapper = wrap();
    render(
      <Wrapper>
        <Opener />
        <CommandPalette />
      </Wrapper>
    );
    fireEvent.click(screen.getByText(/open palette/i));
    await screen.findByText("Backend");
  });

  it("opens via Cmd+K keydown", async () => {
    server.use(
      http.get("http://localhost:8000/api/jobs", () => HttpResponse.json([])),
    );
    const Wrapper = wrap();
    render(
      <Wrapper>
        <Opener />
        <CommandPalette />
      </Wrapper>
    );
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    await screen.findByPlaceholderText(/search/i);
  });
});
