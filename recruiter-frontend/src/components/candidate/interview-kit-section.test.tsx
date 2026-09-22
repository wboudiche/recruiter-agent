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
  capture: { body?: any; sheet?: any; submitted?: boolean; addedTrack?: any; removedTrack?: string } = {},
  opts: { sheets?: unknown[]; me?: { id: number; role: string }; canWrite?: boolean; interviewers?: unknown[]; interviewRound?: number; templateName?: string; tracks?: unknown[]; stage?: string; templates?: unknown[] } = {},
) {
  const me = opts.me ?? { id: 1, role: "recruiter" };
  server.use(
    http.get("http://localhost:8000/api/auth/me", () =>
      HttpResponse.json({ id: me.id, email: "me@acme.com", name: "Me", picture: null, role: me.role })),
    http.get("http://localhost:8000/api/applications/1/interview-kit", () =>
      HttpResponse.json({
        kit, sheets: opts.sheets ?? [], template_name: opts.templateName ?? null,
        ...(opts.tracks ? { tracks: opts.tracks } : {}),
      })),
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
    http.get("http://localhost:8000/api/interview-templates", () =>
      HttpResponse.json(opts.templates ?? [])),
    http.post("http://localhost:8000/api/applications/1/interview-tracks", async ({ request }) => {
      capture.addedTrack = await request.json();
      return HttpResponse.json({ kit, sheets: opts.sheets ?? [], tracks: opts.tracks ?? [] },
                               { status: 201 });
    }),
    http.delete("http://localhost:8000/api/applications/1/interview-tracks/:track", ({ params }) => {
      capture.removedTrack = String(params.track);
      return HttpResponse.json({ kit, sheets: opts.sheets ?? [], tracks: opts.tracks ?? [] });
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}<Toaster /></QueryClientProvider>
  );
  const result = render(<Wrapper><InterviewKitSection applicationId={1} canWrite={opts.canWrite ?? true} interviewRound={opts.interviewRound} stage={opts.stage} /></Wrapper>);
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

  it("still shows the questions when a kit with questions is in error", async () => {
    // A failed regeneration keeps the questions it already had (see
    // run_generate_kit). Rendering only the banner hides a live interview's
    // questions — and the sheets beneath them — behind a message about a
    // generation that failed.
    mountWithKit({ ...READY, status: "error", error: "model unavailable" });

    await waitFor(() =>
      expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());
    expect(screen.getByText(/model unavailable/i)).toBeInTheDocument();
  });

  it("shows an interviewer the questions of an errored kit they cannot retry", async () => {
    // The Retry button is recruiter-only, so for an interviewer the bare
    // error screen is a dead end: no questions, no sheet, no way out.
    mountWithKit(
      { ...READY, status: "error", error: "model unavailable" },
      {},
      {
        me: { id: 7, role: "viewer" },
        canWrite: false,
        sheets: [{ user_id: 7, name: "Panelist", email: "p@acme.com",
                   sheet: { answers: {}, verdict: {} }, submitted_at: null }],
        interviewers: [{ user_id: 7, name: "Panelist", email: "p@acme.com", submitted_at: null }],
      },
    );

    // An interviewer cannot edit questions, so they render as text rather
    // than as a textarea — hence getByText, not getByDisplayValue.
    await waitFor(() =>
      expect(screen.getByText("Why this role?")).toBeInTheDocument());
    expect(screen.getByText(/model unavailable/i)).toBeInTheDocument();
  });

  it("labels the round once an application has been reopened", async () => {
    // Reopening resets every sheet to empty, which looks identical to a
    // round that never happened unless the round is named.
    mountWithKit(READY, {}, { interviewRound: 2 });

    await waitFor(() => expect(screen.getByText(/round 2/i)).toBeInTheDocument());
  });

  it("names the template the round was built from", async () => {
    mountWithKit(
      { status: "ready", questions: [{ id: "q1", text: "Why us?", source: "baseline",
                                       answer: null, rating: null }] },
      {},
      { interviewRound: 2, templateName: "RH screen" },
    );
    expect(await screen.findByText("Round 2 · RH screen")).toBeInTheDocument();
  });

  it("does not label the round during the first one", async () => {
    mountWithKit(READY, {}, { interviewRound: 1 });
    await waitFor(() => expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());
    expect(screen.queryByText(/round 1/i)).not.toBeInTheDocument();
  });

  it("locks the wording of a question answered in a submitted sheet", async () => {
    // The server 409s on this (see patch_kit); offering an editable box that
    // fails on save would be a worse way to find out.
    mountWithKit(READY, {}, {
      sheets: [{
        user_id: 1, name: "Ann", email: "ann@acme.com",
        submitted_at: "2026-09-20T10:00:00Z",
        sheet: { answers: { b1: { answer: "Because scale.", rating: "strong" } }, verdict: {} },
      }],
    });

    // b1 was answered and submitted: read-only. p1 was not: still editable.
    await waitFor(() => expect(screen.getByText("Why this role?")).toBeInTheDocument());
    expect(screen.queryByDisplayValue("Why this role?")).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("Describe an incident.")).toBeInTheDocument();
  });

  it("leaves wording editable while the answer is still a draft", async () => {
    mountWithKit(READY, {}, {
      sheets: [{
        user_id: 1, name: "Ann", email: "ann@acme.com", submitted_at: null,
        sheet: { answers: { b1: { answer: "half a thought", rating: null } }, verdict: {} },
      }],
    });

    await waitFor(() =>
      expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());
  });

  it("gives a recruiter their LIVE round's sheet, not their round-1 one", async () => {
    // A recruiter sees every round's sheets, oldest first. Matching on
    // user_id alone finds the round-1 row, shows it as already submitted,
    // and leaves no way to record round-2 feedback — which also means the
    // round can never close.
    mountWithKit(READY, {}, {
      interviewRound: 2,
      sheets: [
        { user_id: 1, name: "Me", email: "me@acme.com", round: 1,
          submitted_at: "2026-09-20T10:00:00Z",
          sheet: { answers: { b1: { answer: "round one answer", rating: "strong" } },
                   verdict: { decision: "hire", note: null } } },
        { user_id: 1, name: "Me", email: "me@acme.com", round: 2, submitted_at: null,
          sheet: { answers: {}, verdict: { decision: null, note: null } } },
      ],
    });

    // Round 2's sheet is unsubmitted, so the sheet editor must be writable
    // and must NOT be pre-filled with round 1's answer.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /submit interview/i })).toBeInTheDocument());
    expect(screen.queryByDisplayValue("round one answer")).not.toBeInTheDocument();
  });

  it("does not freeze round two's questions because round one was submitted", async () => {
    // The server allows this PATCH (see
    // test_round_two_questions_are_editable_after_round_one_closed). A
    // client-side freeze computed across every round contradicts it: round
    // one's sheets stay submitted forever, so Remove would be disabled for
    // the life of the application.
    mountWithKit(READY, {}, {
      interviewRound: 2,
      sheets: [
        { user_id: 9, name: "Ann", email: "ann@acme.com", round: 1,
          submitted_at: "2026-09-20T10:00:00Z",
          sheet: { answers: {}, verdict: { decision: "hire", note: null } } },
        { user_id: 9, name: "Ann", email: "ann@acme.com", round: 2, submitted_at: null,
          sheet: { answers: {}, verdict: { decision: null, note: null } } },
      ],
    });

    await waitFor(() =>
      expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /remove question 1/i })).toBeEnabled();
  });

  it("re-seeds the sheet editor when a round is reopened", async () => {
    // The seed key is (whose sheet, submitted?). Closing a round manually
    // with an unsubmitted sheet and reopening yields the same key either
    // side — so the editor keeps round one's draft and Save writes it into
    // round two.
    const sheetIn = (round: number, answer: string | null) => ({
      user_id: 1, name: "Me", email: "me@acme.com", round, submitted_at: null,
      sheet: { answers: answer ? { b1: { answer, rating: null } } : {},
               verdict: { decision: null, note: null } },
    });
    let sheets = [sheetIn(1, "round one draft")];
    server.use(
      http.get("http://localhost:8000/api/auth/me", () =>
        HttpResponse.json({ id: 1, email: "me@acme.com", name: "Me", picture: null,
                            role: "recruiter" })),
      http.get("http://localhost:8000/api/applications/1/interview-kit", () =>
        HttpResponse.json({ kit: READY, sheets })),
      http.get("http://localhost:8000/api/applications/1/interviewers", () =>
        HttpResponse.json([])),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const Tree = ({ round }: { round: number }) => (
      <QueryClientProvider client={qc}>
        <InterviewKitSection applicationId={1} canWrite interviewRound={round} />
      </QueryClientProvider>
    );
    const { rerender } = render(<Tree round={1} />);
    await waitFor(() =>
      expect(screen.getByDisplayValue("round one draft")).toBeInTheDocument());

    // Same person, still unsubmitted — but now round two.
    sheets = [sheetIn(2, null)];
    await qc.invalidateQueries({ queryKey: queryKeys.interviewKit(1) });
    rerender(<Tree round={2} />);

    await waitFor(() =>
      expect(screen.queryByDisplayValue("round one draft")).not.toBeInTheDocument());
  });

  it("lets a recruiter write when THIS round has no panel, even with history", async () => {
    // `_own_assignment` auto-creates a row when the LIVE round has none,
    // which is what keeps the zero-setup single-recruiter flow working.
    // Checking every round instead locks the recruiter out of a sheet the
    // server would accept: round one's rows make the list non-empty.
    mountWithKit(READY, {}, {
      interviewRound: 2,
      sheets: [
        { user_id: 9, name: "Ann", email: "ann@acme.com", round: 1,
          submitted_at: "2026-09-20T10:00:00Z",
          sheet: { answers: {}, verdict: { decision: "hire", note: null } } },
      ],
    });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /submit interview/i })).toBeInTheDocument());
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
    // b1 carries a submitted answer, so its wording is now part of the
    // record and renders as read-only text rather than a textarea.
    await screen.findByText("Why this role?");
    expect(screen.queryByDisplayValue("Why this role?")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /submit interview/i })).not.toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();
  });

  it("disables removal and regenerate once any sheet is submitted", async () => {
    const other = { user_id: 7, name: "Bob", email: "bob@acme.com", sheet: { answers: {}, verdict: { decision: null, note: null } }, submitted_at: "2026-09-14T10:00:00Z" };
    mountWithKit(READY, {}, { sheets: [other] });
    await screen.findByDisplayValue("Why this role?");
    expect(screen.getByRole("button", { name: /remove question 1/i })).toBeDisabled();
    // The submitted sheet answered nothing, so no question's wording is part
    // of the record yet: a recruiter can still fix a typo. Only removal and
    // regenerate are refused by the freeze itself.
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

  // R3: after a successful PATCH, the response must land in the cache
  // immediately — not only after the invalidated refetch completes. Proven
  // by making the refetch hang forever: only a direct cache write can make
  // the assertion below observe the new data.
  it("writes the sheet-save response into the cache immediately, without waiting for a refetch (R3)", async () => {
    const mine = { user_id: 1, name: "Me", email: "me@acme.com",
      sheet: { answers: {}, verdict: { decision: null, note: null } }, submitted_at: null };
    const { qc } = mountWithKit(READY, {}, { sheets: [mine] });
    await screen.findByDisplayValue("Why this role?");

    const SAVED_SHEETS = [{ ...mine,
      sheet: { answers: { b1: { answer: "Wants scale", rating: null } }, verdict: { decision: null, note: null } } }];
    server.use(
      http.patch("http://localhost:8000/api/applications/1/interview-kit/sheet", () =>
        HttpResponse.json({ kit: READY, sheets: SAVED_SHEETS })),
      // Never resolves: if the cache only updated via the invalidated
      // refetch, this assertion would never see the saved data.
      http.get("http://localhost:8000/api/applications/1/interview-kit", () => new Promise(() => {})),
    );

    await userEvent.type(screen.getAllByPlaceholderText(/what they said/i)[0], "Wants scale");
    await userEvent.click(screen.getByRole("button", { name: /save answers/i }));

    await waitFor(() => {
      const cached = qc.getQueryData(queryKeys.interviewKit(1)) as any;
      expect(cached?.sheets).toEqual(SAVED_SHEETS);
    });
  });

  it("writes the question-save response into the cache immediately, without waiting for a refetch (R3)", async () => {
    const other = { user_id: 7, name: "Bob", email: "bob@acme.com",
      sheet: { answers: {}, verdict: { decision: null, note: null } }, submitted_at: null };
    const { qc } = mountWithKit(READY, {}, { sheets: [other], me: { id: 1, role: "recruiter" } });
    await screen.findByDisplayValue("Why this role?");

    const UPDATED_KIT = { ...READY, questions: [READY.questions[1]] };
    server.use(
      http.patch("http://localhost:8000/api/applications/1/interview-kit", () =>
        HttpResponse.json({ kit: UPDATED_KIT, sheets: [other] })),
      http.get("http://localhost:8000/api/applications/1/interview-kit", () => new Promise(() => {})),
    );

    await userEvent.click(screen.getByRole("button", { name: /remove question 1/i }));
    await userEvent.click(screen.getByRole("button", { name: /save questions/i }));

    await waitFor(() => {
      const cached = qc.getQueryData(queryKeys.interviewKit(1)) as any;
      expect(cached?.kit?.questions).toEqual(UPDATED_KIT.questions);
    });
  });

  // R2: a colleague's question edit landing between this draft's seed and
  // this Save must never be silently overwritten (or 403 forever for a
  // viewer) by PATCHing the stale draft.
  it("refuses to PATCH stale question edits when the server list changed underneath, but still saves the sheet (R2)", async () => {
    const cap: { body?: any; sheet?: any } = {};
    const { qc } = mountWithKit(READY, cap);
    await screen.findByDisplayValue("Why this role?");

    const field = await screen.findByLabelText("Question 1");
    await userEvent.clear(field);
    await userEvent.type(field, "Why us?");

    const UPDATED = {
      ...READY,
      questions: [
        ...READY.questions,
        { id: "p2", text: "Added by a colleague", source: "probe", criterion: null, answer: null, rating: null },
      ],
    };
    qc.setQueryData(queryKeys.interviewKit(1), { kit: UPDATED, sheets: [] });

    await userEvent.click(screen.getByRole("button", { name: /save answers/i }));

    expect(await screen.findByText(/questions changed on the server/i)).toBeInTheDocument();
    await waitFor(() => expect(cap.sheet).toBeDefined());
    expect(cap.body).toBeUndefined();
  });

  it("discards local question edits and re-seeds from the server on click (R2)", async () => {
    const { qc } = mountWithKit(READY);
    await screen.findByDisplayValue("Why this role?");

    const field = await screen.findByLabelText("Question 1");
    await userEvent.clear(field);
    await userEvent.type(field, "Why us?");

    const UPDATED = {
      ...READY,
      questions: [
        ...READY.questions,
        { id: "p2", text: "Added by a colleague", source: "probe", criterion: null, answer: null, rating: null },
      ],
    };
    qc.setQueryData(queryKeys.interviewKit(1), { kit: UPDATED, sheets: [] });

    const discardButton = await screen.findByRole("button", { name: /discard question edits/i });
    await userEvent.click(discardButton);

    expect(await screen.findByDisplayValue("Added by a colleague")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save answers/i })).toHaveAttribute("data-dirty", "false");
  });

  // R9: a refetch that drops a question a dirty sheet has an unsaved answer
  // for must not re-seed the draft out from under that answer.
  it("keeps a dirty sheet's row on screen when a refetch drops that question underneath it (R9)", async () => {
    const mine = { user_id: 1, name: "Me", email: "me@acme.com",
      sheet: { answers: {}, verdict: { decision: null, note: null } }, submitted_at: null };
    const { qc } = mountWithKit(READY, {}, { sheets: [mine] });
    await screen.findByDisplayValue("Why this role?");

    await userEvent.type(screen.getAllByPlaceholderText(/what they said/i)[0], "Good answer");

    const DROPPED = { ...READY, questions: [READY.questions[1]] };
    qc.setQueryData(queryKeys.interviewKit(1), { kit: DROPPED, sheets: [mine] });

    expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Good answer")).toBeInTheDocument();
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

const q = (id: string, text: string) =>
  ({ id, text, source: "baseline", answer: null, rating: null });
const TECH = { track: "t1", template_id: 1, template_name: "Technical",
               kit: { status: "ready", questions: [q("q1", "Clusters?")] } };
const RH = { track: "t2", template_id: 2, template_name: "RH screen",
             kit: { status: "ready", questions: [q("r1", "Why us?")] } };
const TEMPLATE = (id: number, name: string) => ({ id, name, description: null, questions: [],
  probe_mode: "none", include_job_questions: false, is_active: true });

describe("InterviewKitSection — tracks", () => {
  it("shows one tab per track, each with its own questions", async () => {
    mountWithKit(TECH.kit, {}, { tracks: [TECH, RH] });
    const rhTab = await screen.findByRole("tab", { name: /rh screen/i });
    expect(screen.getByRole("tab", { name: /technical/i })).toHaveAttribute("aria-selected", "true");
    await userEvent.click(rhTab);
    expect(rhTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: /rh screen/i })).toHaveTextContent("Why us?");
  });

  it("adds a track from the templates the round does not have", async () => {
    const capture: { addedTrack?: any } = {};
    mountWithKit(TECH.kit, capture, {
      tracks: [TECH], stage: "scheduled",
      templates: [TEMPLATE(1, "Technical"), TEMPLATE(2, "RH screen")],
    });
    await userEvent.click(await screen.findByRole("button", { name: /add track/i }));
    await userEvent.click(screen.getByRole("combobox", { name: /track template/i }));
    expect(screen.queryByRole("option", { name: "Technical" })).not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole("option", { name: /rh screen/i }));
    await userEvent.click(screen.getByRole("button", { name: /^add track$/i }));
    await waitFor(() => expect(capture.addedTrack).toEqual({ template_id: 2 }));
  });

  it("will not remove a track someone has written in", async () => {
    const capture: { removedTrack?: string } = {};
    mountWithKit(TECH.kit, capture, {
      tracks: [TECH, RH], stage: "scheduled",
      sheets: [{ user_id: 7, name: "Carol", email: "c@acme.com", round: 1, track: "t2",
                 submitted_at: null,
                 sheet: { answers: {}, verdict: { decision: null, note: "promising" } } }],
    });
    expect(await screen.findByRole("button", { name: /remove track rh screen/i })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /remove track technical/i }));
    await waitFor(() => expect(capture.removedTrack).toBe("t1"));
  });

  it("shows an interviewer their one track without tabs", async () => {
    mountWithKit(RH.kit, {}, { tracks: [RH], me: { id: 7, role: "viewer" }, canWrite: false });
    expect(await screen.findByText("Why us?")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.getByText(/rh screen/i)).toBeInTheDocument();
  });
});
