import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { Toaster } from "sonner";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { queryKeys } from "@/lib/query-keys";
import { InterviewKitSection } from "./interview-kit-section";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function mountWithKit(
  kit: unknown,
  capture: { body?: any; sheet?: any; submitted?: boolean } = {},
  opts: { sheets?: unknown[]; me?: { id: number; role: string }; canWrite?: boolean; interviewers?: unknown[] } = {},
) {
  const me = opts.me ?? { id: 1, role: "recruiter" };
  server.use(
    http.get("http://localhost:8000/api/auth/me", () =>
      HttpResponse.json({ id: me.id, email: "me@acme.com", name: "Me", picture: null, role: me.role })),
    http.get("http://localhost:8000/api/applications/1/interview-kit", () =>
      HttpResponse.json({ kit, sheets: opts.sheets ?? [] })),
    http.patch("http://localhost:8000/api/applications/1/interview-kit", async ({ request }) => {
      capture.body = await request.json();
      return HttpResponse.json({ kit, sheets: opts.sheets ?? [] });
    }),
    http.patch("http://localhost:8000/api/applications/1/interview-kit/sheet", async ({ request }) => {
      capture.sheet = await request.json();
      return HttpResponse.json({ kit, sheets: opts.sheets ?? [] });
    }),
    http.post("http://localhost:8000/api/applications/1/interview-kit/sheet/submit", () => {
      capture.submitted = true;
      return HttpResponse.json({ kit, sheets: opts.sheets ?? [] });
    }),
    http.post("http://localhost:8000/api/applications/1/interview-kit/generate", () =>
      HttpResponse.json({ application_id: 1 }, { status: 202 })),
    http.get("http://localhost:8000/api/applications/1/interviewers", () =>
      HttpResponse.json(opts.interviewers ?? [])),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}<Toaster /></QueryClientProvider>
  );
  const result = render(<Wrapper><InterviewKitSection applicationId={1} canWrite={opts.canWrite ?? true} /></Wrapper>);
  return { ...result, qc };
}

const READY = {
  status: "ready",
  questions: [
    { id: "b1", text: "Why this role?", source: "baseline", answer: null, rating: null },
    { id: "p1", text: "Describe an incident.", source: "probe",
      criterion: "Kubernetes", answer: null, rating: null },
  ],
};

describe("InterviewKitSection", () => {
  it("offers Generate when there is no kit", async () => {
    mountWithKit(null);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /generate interview kit/i })).toBeInTheDocument(),
    );
  });

  it("shows a loader while generating", async () => {
    mountWithKit({ status: "generating", questions: [] });
    await waitFor(() => expect(screen.getByText(/generating/i)).toBeInTheDocument());
  });

  it("shows the error and a retry when generation failed", async () => {
    mountWithKit({ status: "error", error: "model unavailable", questions: [] });
    await waitFor(() => expect(screen.getByText(/model unavailable/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("renders questions with their source badge", async () => {
    mountWithKit(READY);
    await waitFor(() => expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());
    expect(screen.getByText(/^Role$/)).toBeInTheDocument();
    expect(screen.getByText(/for this candidate/i)).toBeInTheDocument();
  });

  it("renders each question in a multi-line field so long text wraps instead of clipping", async () => {
    const LONG = "Can you describe a specific instance where you mentored a junior engineer or led a "
      + "small team through a challenging DevOps project? What was the outcome and what would you "
      + "do differently next time?";
    mountWithKit({ ...READY, questions: [{ ...READY.questions[0], text: LONG }] });
    const field = await screen.findByLabelText("Question 1");
    // A single-line <input> can only scroll horizontally; only a textarea
    // lets the browser wrap the question onto as many lines as it needs.
    expect(field.tagName).toBe("TEXTAREA");
    expect(field).toHaveValue(LONG);
  });

  it("saves an edit made through the question field", async () => {
    const capture: { body?: any } = {};
    mountWithKit(READY, capture);
    const field = await screen.findByLabelText("Question 1");
    await userEvent.clear(field);
    await userEvent.type(field, "Why us?");
    await userEvent.click(screen.getByRole("button", { name: /save answers/i }));
    await waitFor(() => expect(capture.body).toBeDefined());
    expect(capture.body.questions[0].text).toBe("Why us?");
  });

  it("gives each rating button a name that identifies its question", async () => {
    mountWithKit(READY);
    await waitFor(() => expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());

    // Two questions each render Strong/Adequate/Weak; the visible text alone
    // would be ambiguous, so each button must resolve uniquely by name.
    expect(screen.getByRole("button", { name: /rate question 1 as strong/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /rate question 2 as strong/i })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /rate question 1 as strong/i }),
    ).not.toBe(screen.getByRole("button", { name: /rate question 2 as strong/i }));
  });

  it("adds a question and includes it when saving", async () => {
    const cap: { body?: any } = {};
    mountWithKit(READY, cap);
    await waitFor(() => expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: /add question/i }));
    const inputs = screen.getAllByLabelText(/^Question \d+$/i);
    await userEvent.type(inputs[inputs.length - 1], "Anything to ask us?");
    await userEvent.click(screen.getByRole("button", { name: /save answers/i }));

    await waitFor(() => expect(cap.body).toBeDefined());
    expect(cap.body.questions.map((q: any) => q.text)).toContain("Anything to ask us?");
  });

  it("mints distinct ids for questions added back-to-back", async () => {
    const cap: { body?: any } = {};
    mountWithKit(READY, cap);
    await waitFor(() => expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());

    // Two Adds in immediate succession must not collide on id (e.g. both
    // minted from the same Date.now() millisecond) — a collision would make
    // `update`/remove, which match by id, silently act on both rows.
    await userEvent.click(screen.getByRole("button", { name: /add question/i }));
    await userEvent.click(screen.getByRole("button", { name: /add question/i }));
    const inputs = screen.getAllByLabelText(/^Question \d+$/i);
    await userEvent.type(inputs[inputs.length - 2], "First new");
    await userEvent.type(inputs[inputs.length - 1], "Second new");
    await userEvent.click(screen.getByRole("button", { name: /save answers/i }));

    await waitFor(() => expect(cap.body).toBeDefined());
    const added = cap.body.questions.filter(
      (q: any) => q.text === "First new" || q.text === "Second new",
    );
    expect(added).toHaveLength(2);
    expect(added[0].id).not.toBe(added[1].id);
  });

  it("removes a question", async () => {
    const cap: { body?: any } = {};
    mountWithKit(READY, cap);
    await waitFor(() => expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: /remove question 1/i }));
    await userEvent.click(screen.getByRole("button", { name: /save answers/i }));

    await waitFor(() => expect(cap.body).toBeDefined());
    expect(cap.body.questions.map((q: any) => q.text)).not.toContain("Why this role?");
  });

  it("shows an error toast and does not lose the draft when saving fails", async () => {
    mountWithKit(READY);
    await waitFor(() => expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());
    server.use(
      http.patch("http://localhost:8000/api/applications/1/interview-kit/sheet", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    await userEvent.type(screen.getAllByPlaceholderText(/what they said/i)[0], "Wants scale");
    await userEvent.click(screen.getByRole("button", { name: /save answers/i }));

    expect(await screen.findByText(/boom/i)).toBeInTheDocument();
    // The failed save must not wipe what the recruiter typed.
    expect(screen.getByDisplayValue("Wants scale")).toBeInTheDocument();
  });

  it("marks Save dirty once the draft diverges, and clean again after saving", async () => {
    const capture: { sheet?: any } = {};
    mountWithKit(READY, capture);
    await waitFor(() => expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());

    const saveButton = screen.getByRole("button", { name: /save answers/i });
    expect(saveButton).toHaveAttribute("data-dirty", "false");

    await userEvent.type(screen.getAllByPlaceholderText(/what they said/i)[0], "Wants scale");
    expect(saveButton).toHaveAttribute("data-dirty", "true");

    await userEvent.click(saveButton);
    await waitFor(() => expect(capture.sheet).toBeDefined());
    expect(capture.sheet.answers.b1.answer).toBe("Wants scale");
  });

  it("warns before unload while the draft is dirty, not once saved", async () => {
    mountWithKit(READY);
    await waitFor(() => expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());

    const cleanEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(cleanEvent);
    expect(cleanEvent.defaultPrevented).toBe(false);

    await userEvent.type(screen.getAllByPlaceholderText(/what they said/i)[0], "Wants scale");

    const dirtyEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirtyEvent);
    expect(dirtyEvent.defaultPrevented).toBe(true);
  });

  it("shows a distinct error state with retry when the kit request fails", async () => {
    server.use(
      http.get("http://localhost:8000/api/auth/me", () =>
        HttpResponse.json({ id: 1, email: "me@acme.com", name: "Me", picture: null, role: "recruiter" })),
      http.get("http://localhost:8000/api/applications/1/interview-kit", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
      http.get("http://localhost:8000/api/applications/1/interviewers", () =>
        HttpResponse.json([])),
    );
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={qc}>
        <InterviewKitSection applicationId={1} canWrite />
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(screen.getByText(/couldn.t load the interview kit/i)).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
    // Distinct from the absent-kit state, which offers Generate instead.
    expect(
      screen.queryByRole("button", { name: /generate interview kit/i }),
    ).not.toBeInTheDocument();
  });

  it("hides every write control for a viewer", async () => {
    mountWithKit(READY, {}, { canWrite: false });
    await waitFor(() => expect(screen.getByText("Why this role?")).toBeInTheDocument());

    // No mutation-triggering controls at all — not just Save/Submit.
    expect(screen.queryByRole("button", { name: /save answers/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /submit interview/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add question/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /remove question/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /rate question/i })).not.toBeInTheDocument();
    // The question text must not be editable.
    expect(screen.queryByLabelText(/^Question \d+$/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /^Question \d+$/i })).not.toBeInTheDocument();
  });

  it("drafts a question with AI and appends it as an editable row", async () => {
    let hintSent: unknown;
    server.use(
      http.post(
        "http://localhost:8000/api/applications/1/interview-kit/draft-question",
        async ({ request }) => {
          hintSent = ((await request.json()) as { hint?: string }).hint;
          return HttpResponse.json({
            question: { text: "How do you handle Terraform state locking?", criterion: "IaC" },
          });
        },
      ),
    );
    mountWithKit(READY);
    await waitFor(() => expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());

    await userEvent.type(screen.getByPlaceholderText(/about/i), "Terraform state locking");
    await userEvent.click(screen.getByRole("button", { name: /draft with ai/i }));

    // Lands as an ordinary editable row, so it is read and can be reworded
    // before Save ever writes it to the record.
    await waitFor(() =>
      expect(
        screen.getByDisplayValue("How do you handle Terraform state locking?"),
      ).toBeInTheDocument(),
    );
    expect(hintSent).toBe("Terraform state locking");
  });

  it("sends a null hint when the box is empty", async () => {
    let hintSent: unknown = "unset";
    server.use(
      http.post(
        "http://localhost:8000/api/applications/1/interview-kit/draft-question",
        async ({ request }) => {
          hintSent = ((await request.json()) as { hint?: string | null }).hint;
          return HttpResponse.json({ question: { text: "Anything?", criterion: null } });
        },
      ),
    );
    mountWithKit(READY);
    await waitFor(() => expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: /draft with ai/i }));

    await waitFor(() => expect(hintSent).toBeNull());
  });

  it("surfaces a failed draft instead of silently doing nothing", async () => {
    server.use(
      http.post(
        "http://localhost:8000/api/applications/1/interview-kit/draft-question",
        () => HttpResponse.json({ detail: "Could not draft a question" }, { status: 502 }),
      ),
    );
    mountWithKit(READY);
    await waitFor(() => expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: /draft with ai/i }));

    await waitFor(() =>
      expect(screen.getByText(/could not draft/i)).toBeInTheDocument(),
    );
  });

  it("offers no AI drafting to a viewer", async () => {
    mountWithKit(READY, {}, { canWrite: false });
    await waitFor(() => expect(screen.getByText("Why this role?")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /draft with ai/i })).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/about/i)).not.toBeInTheDocument();
  });

  it("saves answers and ratings to the caller's sheet", async () => {
    const capture: { sheet?: any } = {};
    mountWithKit(READY, capture);
    await screen.findByDisplayValue("Why this role?");
    // Both questions get an answer box; the assertion below is scoped to
    // b1 (question 1), so type into the first one.
    await userEvent.type(screen.getAllByPlaceholderText(/what they said/i)[0], "Good answer");
    await userEvent.click(screen.getByRole("button", { name: /rate question 1 as strong/i }));
    await userEvent.click(screen.getByRole("button", { name: /save answers/i }));
    await waitFor(() => expect(capture.sheet).toBeDefined());
    expect(capture.sheet.answers.b1).toEqual({ answer: "Good answer", rating: "strong" });
  });

  it("records a verdict on the sheet", async () => {
    const capture: { sheet?: any } = {};
    mountWithKit(READY, capture);
    await screen.findByDisplayValue("Why this role?");
    await userEvent.click(screen.getByRole("button", { name: /^hire$/i }));
    await userEvent.type(screen.getByLabelText(/verdict note/i), "Strong on infra.");
    await userEvent.click(screen.getByRole("button", { name: /save answers/i }));
    await waitFor(() => expect(capture.sheet?.verdict).toEqual({ decision: "hire", note: "Strong on infra." }));
  });

  it("asks before submitting with unanswered questions, then submits the sheet", async () => {
    const capture: { sheet?: any; submitted?: boolean } = {};
    mountWithKit(READY, capture);
    await screen.findByDisplayValue("Why this role?");
    await userEvent.click(screen.getByRole("button", { name: /submit interview/i }));
    expect(await screen.findByRole("dialog")).toHaveTextContent(/2 question\(s\) have no answer/);
    await userEvent.click(screen.getByRole("button", { name: /submit anyway/i }));
    await waitFor(() => expect(capture.submitted).toBe(true));
  });

  it("renders a submitted sheet read-only", async () => {
    const mine = { user_id: 1, name: "Me", email: "me@acme.com",
      sheet: { answers: { b1: { answer: "Done", rating: "weak" } }, verdict: { decision: "no_hire", note: null } },
      submitted_at: "2026-09-14T10:00:00Z" };
    mountWithKit(READY, {}, { sheets: [mine] });
    // Question ids are stable, so renaming stays allowed even once frozen —
    // the row is still an editable textarea, not read-only text.
    await screen.findByDisplayValue("Why this role?");
    expect(screen.queryByRole("button", { name: /submit interview/i })).not.toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();
  });

  it("disables removal and regenerate once any sheet is submitted", async () => {
    const other = { user_id: 7, name: "Bob", email: "bob@acme.com", sheet: { answers: {}, verdict: { decision: null, note: null } }, submitted_at: "2026-09-14T10:00:00Z" };
    mountWithKit(READY, {}, { sheets: [other] });
    await screen.findByDisplayValue("Why this role?");
    expect(screen.getByRole("button", { name: /remove question 1/i })).toBeDisabled();
    // Freezing only refuses removal (and regenerate) — the question text
    // itself stays editable for a recruiter/admin.
    expect(screen.getByLabelText("Question 1")).toBeEnabled();
  });

  it("locks out a recruiter with no panel row on a kit that already has one", async () => {
    const other = { user_id: 7, name: "Bob", email: "bob@acme.com", sheet: { answers: {}, verdict: { decision: null, note: null } }, submitted_at: null };
    const cap: { body?: any; sheet?: any } = {};
    mountWithKit(READY, cap, { sheets: [other], me: { id: 1, role: "recruiter" } });
    await screen.findByDisplayValue("Why this role?");
    expect(screen.queryByPlaceholderText(/what they said/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /submit interview/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /remove question 1/i })).toBeInTheDocument();

    // No sheet to write, but question edits must still be saveable.
    await userEvent.click(screen.getByRole("button", { name: /remove question 1/i }));
    await userEvent.click(screen.getByRole("button", { name: /save questions/i }));

    await waitFor(() => expect(cap.body).toBeDefined());
    expect(cap.body.questions).toHaveLength(1);
    expect(cap.sheet).toBeUndefined();
  });

  it("lets a submitted interviewer keep saving question edits with no sheet to write", async () => {
    const mine = {
      user_id: 5, name: "V", email: "v@acme.com",
      sheet: { answers: {}, verdict: { decision: null, note: null } },
      submitted_at: "2026-09-14T10:00:00Z",
    };
    const cap: { body?: any; sheet?: any } = {};
    mountWithKit(READY, cap, { sheets: [mine], me: { id: 5, role: "viewer" }, canWrite: false });
    await screen.findByText("Why this role?");

    expect(screen.getByRole("button", { name: /add question/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /add question/i }));
    const inputs = screen.getAllByLabelText(/^Question \d+$/i);
    expect(inputs[inputs.length - 1]).toHaveAccessibleName("Question 3");
    await userEvent.type(inputs[inputs.length - 1], "One more thing?");

    await userEvent.click(screen.getByRole("button", { name: /save questions/i }));

    await waitFor(() => expect(cap.body).toBeDefined());
    expect(cap.body.questions).toHaveLength(3);
    expect(cap.sheet).toBeUndefined();
  });

  it("shows legacy per-question answers read-only", async () => {
    const legacy = { ...READY, questions: [{ ...READY.questions[0], answer: "Old answer", rating: "strong" }] };
    mountWithKit(legacy);
    await screen.findByDisplayValue("Why this role?");
    expect(screen.getByText(/recorded before interviewer sheets/i)).toBeInTheDocument();
    expect(screen.getByText("Old answer")).toBeInTheDocument();
  });

  it("resolves an added-by id to the interviewer's name", async () => {
    const other = { user_id: 7, name: "Bob", email: "bob@acme.com", sheet: { answers: {}, verdict: { decision: null, note: null } }, submitted_at: null };
    const withAddedBy = { ...READY, questions: [{ ...READY.questions[0], added_by: 7 }, READY.questions[1]] };
    mountWithKit(withAddedBy, {}, { sheets: [other] });
    await screen.findByDisplayValue("Why this role?");
    expect(screen.getByText(/added by bob/i)).toBeInTheDocument();
  });

  it("resolves an added-by id via the interviewer roster when no sheet names them yet", async () => {
    const withAddedBy = { ...READY, questions: [{ ...READY.questions[0], added_by: 9 }, READY.questions[1]] };
    mountWithKit(withAddedBy, {}, { interviewers: [{ user_id: 9, name: "Priya", email: "priya@acme.com", submitted_at: null }] });
    await screen.findByDisplayValue("Why this role?");
    expect(screen.getByText(/added by priya/i)).toBeInTheDocument();
  });

  it("falls back to a generic label when the added-by id resolves to nobody known", async () => {
    const withAddedBy = { ...READY, questions: [{ ...READY.questions[0], added_by: 42 }, READY.questions[1]] };
    mountWithKit(withAddedBy);
    await screen.findByDisplayValue("Why this role?");
    expect(screen.getByText(/added by another interviewer/i)).toBeInTheDocument();
  });

  it("gives an assigned viewer only Add question on the question list", async () => {
    const mine = { user_id: 5, name: "V", email: "v@acme.com", sheet: { answers: {}, verdict: { decision: null, note: null } }, submitted_at: null };
    mountWithKit(READY, {}, { sheets: [mine], me: { id: 5, role: "viewer" }, canWrite: false });
    await screen.findByText("Why this role?");
    expect(screen.getByRole("button", { name: /add question/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /remove question 1/i })).not.toBeInTheDocument();
    expect(screen.getAllByPlaceholderText(/what they said/i)[0]).toBeInTheDocument();
  });

  // F1: the question draft used to be resent unconditionally whenever it
  // differed (by JSON) from the last-seen server questions. A background
  // refetch that updated `kit.questions` (someone else's edit) without the
  // draft being re-seeded meant an unrelated "Save answers" click could
  // resend a stale question list and silently drop a colleague's question.
  // An explicit `questionsDirty` flag, set only by the user's own edits,
  // fixes this.
  it("saves only the sheet, never the question list, when only an answer changed (F1)", async () => {
    const mine = {
      user_id: 5, name: "V", email: "v@acme.com",
      sheet: { answers: {}, verdict: { decision: null, note: null } },
      submitted_at: null,
    };
    const capture: { body?: any; sheet?: any } = {};
    mountWithKit(READY, capture, { sheets: [mine], me: { id: 5, role: "viewer" }, canWrite: false });
    await screen.findByText("Why this role?");

    await userEvent.type(screen.getAllByPlaceholderText(/what they said/i)[0], "Good answer");
    await userEvent.click(screen.getByRole("button", { name: /save answers/i }));

    await waitFor(() => expect(capture.sheet).toBeDefined());
    // No question PATCH must have been sent at all.
    expect(capture.body).toBeUndefined();
  });

  it("re-seeds the untouched draft when the server's question list changes underneath it (F1)", async () => {
    const { qc } = mountWithKit(READY);
    await screen.findByDisplayValue("Why this role?");

    const UPDATED = {
      ...READY,
      questions: [
        ...READY.questions,
        { id: "p2", text: "Added by a colleague", source: "probe", criterion: null, answer: null, rating: null },
      ],
    };
    server.use(
      http.get("http://localhost:8000/api/applications/1/interview-kit", () =>
        HttpResponse.json({ kit: UPDATED, sheets: [] })),
    );
    await qc.invalidateQueries({ queryKey: queryKeys.interviewKit(1) });

    // No user action taken — the new question must appear on its own.
    await waitFor(() =>
      expect(screen.getByDisplayValue("Added by a colleague")).toBeInTheDocument(),
    );
  });

  it("does not resend a question PATCH on a second save once nothing has changed since (F1)", async () => {
    const cap: { body?: any } = {};
    mountWithKit(READY, cap);
    await screen.findByDisplayValue("Why this role?");

    let patchCalls = 0;
    server.use(
      http.patch("http://localhost:8000/api/applications/1/interview-kit", async ({ request }) => {
        patchCalls += 1;
        cap.body = await request.json();
        return HttpResponse.json({ kit: READY, sheets: [] });
      }),
    );

    await userEvent.click(screen.getByRole("button", { name: /remove question 1/i }));
    await userEvent.click(screen.getByRole("button", { name: /save answers/i }));
    await waitFor(() => expect(patchCalls).toBe(1));

    // Nothing else changed the draft — a second Save must not re-PATCH.
    await userEvent.click(screen.getByRole("button", { name: /save answers/i }));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(patchCalls).toBe(1);
  });

  // F3: guard against a double-submit while a save/patch/submit is in flight.
  it("disables Save while a save is in flight, and re-enables once it resolves (F3)", async () => {
    mountWithKit(READY);
    await screen.findByDisplayValue("Why this role?");

    server.use(
      http.patch("http://localhost:8000/api/applications/1/interview-kit/sheet", async () => {
        await delay(200);
        return HttpResponse.json({ kit: READY, sheets: [] });
      }),
    );

    const saveButton = screen.getByRole("button", { name: /save answers/i });
    await userEvent.click(saveButton);

    await waitFor(() => expect(saveButton).toBeDisabled());
    await waitFor(() => expect(saveButton).toBeEnabled(), { timeout: 3000 });
  });
});
