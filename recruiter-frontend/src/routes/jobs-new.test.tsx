// recruiter-frontend/src/routes/jobs-new.test.tsx
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { Toaster } from "sonner";
import JobsNew from "./jobs-new";

const server = setupServer();

function renderJobsNew() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <JobsNew />
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("JobsNew — Suggest from JD", () => {
  beforeEach(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => {
    server.resetHandlers();
    server.close();
  });

  it("disables the button while the description is short", async () => {
    renderJobsNew();
    const btn = screen.getByRole("button", { name: /suggest from jd/i });
    expect(btn).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/description/i), "short text");
    expect(btn).toBeDisabled();
  });

  it("enables the button when description reaches 50 chars", async () => {
    renderJobsNew();
    await userEvent.type(
      screen.getByLabelText(/description/i),
      "a".repeat(60),
    );
    expect(screen.getByRole("button", { name: /suggest from jd/i })).toBeEnabled();
  });

  it("populates criteria when clicked on an empty list", async () => {
    server.use(
      http.post("http://localhost:8000/api/jobs/criteria/suggest", async () =>
        HttpResponse.json({
          criteria: [
            { name: "Java", weight: 0.5, description: "Java expertise" },
            { name: "Spring", weight: 0.3, description: "Spring framework" },
            { name: "SQL", weight: 0.2, description: "Database skills" },
          ],
        }),
      ),
    );
    renderJobsNew();
    await userEvent.type(screen.getByLabelText(/description/i), "a".repeat(60));
    await userEvent.click(screen.getByRole("button", { name: /suggest from jd/i }));

    await waitFor(() => {
      expect(screen.getByDisplayValue("Java")).toBeInTheDocument();
      expect(screen.getByDisplayValue("Spring")).toBeInTheDocument();
      expect(screen.getByDisplayValue("SQL")).toBeInTheDocument();
    });
  });

  it("shows confirm dialog when criteria already exist; cancel preserves rows", async () => {
    renderJobsNew();
    await userEvent.type(screen.getByLabelText(/description/i), "a".repeat(60));

    // Add a manual criterion first.
    await userEvent.click(screen.getByRole("button", { name: /add criterion/i }));
    const nameInput = await screen.findByPlaceholderText("Name");
    await userEvent.type(nameInput, "MyCustom");

    await userEvent.click(screen.getByRole("button", { name: /suggest from jd/i }));

    // Confirm dialog appears.
    expect(await screen.findByText(/replace 1 existing/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^cancel$/i }));

    // Manual row preserved.
    expect(screen.getByDisplayValue("MyCustom")).toBeInTheDocument();
  });

  it("replaces criteria when confirm dialog is accepted", async () => {
    server.use(
      http.post("http://localhost:8000/api/jobs/criteria/suggest", async () =>
        HttpResponse.json({
          criteria: [
            { name: "Java", weight: 0.5, description: "x" },
            { name: "Spring", weight: 0.3, description: "y" },
            { name: "SQL", weight: 0.2, description: "z" },
          ],
        }),
      ),
    );
    renderJobsNew();
    await userEvent.type(screen.getByLabelText(/description/i), "a".repeat(60));
    await userEvent.click(screen.getByRole("button", { name: /add criterion/i }));
    await userEvent.type(await screen.findByPlaceholderText("Name"), "MyCustom");

    await userEvent.click(screen.getByRole("button", { name: /suggest from jd/i }));
    await userEvent.click(await screen.findByRole("button", { name: /replace/i }));

    await waitFor(() => {
      expect(screen.queryByDisplayValue("MyCustom")).not.toBeInTheDocument();
      expect(screen.getByDisplayValue("Java")).toBeInTheDocument();
    });
  });

  it("shows error toast on 500 and leaves criteria untouched", async () => {
    server.use(
      http.post("http://localhost:8000/api/jobs/criteria/suggest", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    renderJobsNew();
    await userEvent.type(screen.getByLabelText(/description/i), "a".repeat(60));
    await userEvent.click(screen.getByRole("button", { name: /suggest from jd/i }));

    expect(await screen.findByText(/couldn't suggest criteria/i)).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Name")).not.toBeInTheDocument();
  });
});
