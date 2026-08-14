import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { UsersTab } from "./users-tab";

const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: apiMock };
});

const USERS = [
  { id: 1, email: "boss@acme.com", name: "Boss", role: "admin", is_active: true, last_login_at: null },
  { id: 2, email: "rec@acme.com", name: null, role: "recruiter", is_active: true, last_login_at: null },
];

function renderTab() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <UsersTab />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiMock.mockReset();
  apiMock.mockImplementation((path: string) =>
    path === "/api/users" ? Promise.resolve(USERS) : Promise.resolve({}),
  );
});

describe("UsersTab", () => {
  it("lists users with their roles", async () => {
    renderTab();

    expect(await screen.findByText("boss@acme.com")).toBeInTheDocument();
    expect(screen.getByText("rec@acme.com")).toBeInTheDocument();
  });

  it("notes that viewer restrictions are not enforced yet", async () => {
    // M4: the role selector offers "Viewer" but nothing enforces it yet
    // (Slice 2) — a viewer today can do everything a recruiter can.
    // Shipping the selector without a caveat implies read-only
    // behaviour that doesn't exist.
    renderTab();
    await screen.findByText("boss@acme.com");

    expect(screen.getByText(/viewer/i, { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText(/not.*enforced/i)).toBeInTheDocument();
  });

  it("deactivates a user through PATCH", async () => {
    renderTab();
    await screen.findByText("rec@acme.com");

    await userEvent.click(screen.getByRole("button", { name: /deactivate rec@acme.com/i }));

    await waitFor(() =>
      expect(apiMock).toHaveBeenCalledWith("/api/users/2", {
        method: "PATCH",
        json: { is_active: false },
      }),
    );
  });
});
