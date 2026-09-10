import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
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
    // First GET (initial load) returns "Why this role?"; every GET after
    // that returns different question text with the SAME `updated_at`,
    // mirroring an unrelated candidate's stage change: the underlying job
    // record itself did not change, but a refetch still returns a fresh
    // object identity. A buggy implementation keyed on `job.data` identity
    // would visibly overwrite the recruiter's typed text with the server's
    // new text; the fix, keyed on `updated_at`, must not.
    let getCount = 0;
    server.use(
      http.get("http://localhost:8000/api/jobs/1", () => {
        getCount += 1;
        return HttpResponse.json({
          id: 1,
          title: "SRE",
          criteria: [],
          interview_baseline: [
            {
              id: "b1",
              text: getCount === 1 ? "Why this role?" : "Server changed this",
            },
          ],
          updated_at: "2026-01-01T00:00:00Z",
        });
      }),
    );
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const Wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    render(
      <Wrapper>
        <EditInterviewBaselineSheet jobId={1} open onOpenChange={() => {}} canWrite />
      </Wrapper>,
    );
    await waitFor(() =>
      expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument(),
    );

    const input = screen.getByLabelText("Baseline question 1");
    await userEvent.clear(input);
    await userEvent.type(input, "Edited but not yet saved");

    // Simulate handleServerEvent's `["jobs"]`, exact: false invalidation —
    // fired by any stage/error SSE event anywhere, not just this job.
    // react-query's notifyManager always defers subscriber notification to
    // a real macrotask (`setTimeout(fn, 0)`, not a microtask), and React
    // flushes the resulting passive effect on a further tick of its own.
    // Awaiting the refetch promise alone only flushes microtasks, so the
    // component has not necessarily re-rendered yet when it resolves.
    // Flush a handful of real macrotasks (inside `act`, so React accepts
    // the state updates they trigger) to let both of those settle before
    // asserting, for either implementation under test.
    await act(async () => {
      await qc.refetchQueries({ queryKey: ["jobs", 1] });
      for (let i = 0; i < 5; i++) {
        await new Promise((resolve) => setTimeout(resolve, 0));
      }
    });
    expect(getCount).toBeGreaterThan(1);

    expect(screen.getByDisplayValue("Edited but not yet saved")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Server changed this")).not.toBeInTheDocument();
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
