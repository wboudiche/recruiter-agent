import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { EditInterviewBaselineSheet } from "./edit-interview-baseline-sheet";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function mount(capture: { body?: any }, canWrite = true) {
  server.use(
    http.get("http://localhost:8000/api/jobs/1", () =>
      HttpResponse.json({ id: 1, title: "SRE", criteria: [],
                          interview_baseline: [{ id: "b1", text: "Why this role?" }],
                          updated_at: "2026-01-01T00:00:00Z" }),
    ),
    http.put("http://localhost:8000/api/jobs/1/interview-baseline", async ({ request }) => {
      capture.body = await request.json();
      return HttpResponse.json({ id: 1, title: "SRE", criteria: [], interview_baseline: [] });
    }),
  );
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  const result = render(
    <Wrapper>
      <EditInterviewBaselineSheet
        jobId={1}
        open
        onOpenChange={() => {}}
        canWrite={canWrite}
      />
    </Wrapper>,
  );
  return { ...result, qc };
}

describe("EditInterviewBaselineSheet", () => {
  it("loads the existing baseline questions", async () => {
    mount({});
    await waitFor(() =>
      expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument(),
    );
  });

  it("adds a question and saves it", async () => {
    const cap: { body?: any } = {};
    mount(cap);
    await waitFor(() =>
      expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByRole("button", { name: /add question/i }));
    const inputs = screen.getAllByLabelText(/baseline question/i);
    await userEvent.type(inputs[inputs.length - 1], "Notice period?");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(cap.body).toBeDefined());
    expect(cap.body.questions.map((q: any) => q.text)).toContain("Notice period?");
  });

  it("does not send a question left blank", async () => {
    const cap: { body?: any } = {};
    mount(cap);
    await waitFor(() =>
      expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByRole("button", { name: /add question/i }));
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(cap.body).toBeDefined());
    expect(cap.body.questions).toHaveLength(1);
  });

  it("gives each row's input and remove button a name keyed on its position", async () => {
    mount({});
    await waitFor(() =>
      expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByRole("button", { name: /add question/i }));
    await userEvent.click(screen.getByRole("button", { name: /add question/i }));

    expect(screen.getByLabelText("Baseline question 1")).toBeInTheDocument();
    expect(screen.getByLabelText("Baseline question 2")).toBeInTheDocument();
    expect(screen.getByLabelText("Baseline question 3")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Remove question 2" }),
    ).toBeInTheDocument();
  });

  it("keeps a typed edit through a background refetch of the job (e.g. SSE)", async () => {
    const { qc } = mount({});
    await waitFor(() =>
      expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument(),
    );

    const input = screen.getByLabelText("Baseline question 1");
    await userEvent.clear(input);
    await userEvent.type(input, "Edited but not yet saved");

    // Simulate handleServerEvent's `["jobs"]`, exact: false invalidation —
    // fired by any stage/error SSE event anywhere, not just this job — and
    // wait for the resulting background refetch to actually land. The
    // mocked GET returns the same `updated_at` every time, so a correct
    // implementation must not reset `rows` from it.
    await qc.refetchQueries({ queryKey: ["jobs", 1] });

    expect(screen.getByDisplayValue("Edited but not yet saved")).toBeInTheDocument();
  });

  it("shows the questions but hides every write control for a viewer", async () => {
    mount({}, false);
    await waitFor(() =>
      expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument(),
    );

    expect(
      screen.queryByRole("button", { name: /add question/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /remove question/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^save$/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("Why this role?")).toHaveAttribute("readonly");
  });
});
