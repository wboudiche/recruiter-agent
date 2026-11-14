import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { Toaster } from "sonner";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { InterviewTemplateSheet } from "./interview-template-sheet";
import type { InterviewTemplate } from "@/hooks/use-interview-templates";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const TECH: InterviewTemplate = {
  id: 4, name: "Technical — Data Science", description: "Modelling",
  questions: [{ id: "q1", text: "Q1" }],
  probe_mode: "score_gaps", include_job_questions: true, is_active: true,
};
const JOBS = [
  { id: 2, title: "Old role", description: "x", status: "closed", criteria: [],
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
  { id: 7, title: "Data Scientist", description: "Churn models", status: "open", criteria: [],
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
];

function mount(
  template: InterviewTemplate | null,
  capture: { body?: any } = {},
  reply: () => Response = () => HttpResponse.json({
    questions: [{ text: "S1", criterion: "modelling" }, { text: "S2", criterion: null }],
  }) as Response,
) {
  server.use(
    http.get("http://localhost:8000/api/jobs", () => HttpResponse.json(JOBS)),
    http.post("http://localhost:8000/api/interview-templates/suggest-questions",
      async ({ request }) => { capture.body = await request.json(); return reply(); }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <InterviewTemplateSheet template={template} open onOpenChange={() => {}} />
      <Toaster />
    </QueryClientProvider>,
  );
}

const suggestButton = () => screen.getByRole("button", { name: /suggest questions/i });
const questionTexts = () =>
  screen.getAllByRole("textbox", { name: /^Template question \d+$/ })
    .map((el) => (el as HTMLInputElement).value);

describe("InterviewTemplateSheet — Suggest questions", () => {
  it("disables Suggest questions until the template has a name", async () => {
    mount(null);
    expect(suggestButton()).toBeDisabled();
    const name = screen.getByLabelText("Name");
    await userEvent.type(name, "   ");
    expect(suggestButton()).toBeDisabled();
    await userEvent.type(name, "Data");
    expect(suggestButton()).toBeEnabled();
  });

  it("appends suggestions below the existing rows", async () => {
    mount(TECH);
    await userEvent.click(suggestButton());
    await waitFor(() => expect(questionTexts()).toEqual(["Q1", "S1", "S2"]));
  });

  it("sends the kind, the chosen job and only non-blank existing texts", async () => {
    const capture: { body?: any } = {};
    mount(TECH, capture);
    await userEvent.click(screen.getByRole("button", { name: /add question/i }));
    await userEvent.click(screen.getByRole("combobox", { name: /based on job/i }));
    await userEvent.click(await screen.findByRole("option", { name: "Data Scientist" }));
    await userEvent.click(suggestButton());
    await waitFor(() => expect(capture.body).toBeDefined());
    expect(capture.body).toEqual({
      name: "Technical — Data Science", description: "Modelling", kind: "technical",
      job_id: 7, existing: ["Q1"],
    });
  });

  it("sends no job by default", async () => {
    const capture: { body?: any } = {};
    mount(TECH, capture);
    await userEvent.click(suggestButton());
    await waitFor(() => expect(capture.body).toBeDefined());
    expect(capture.body.job_id).toBeNull();
  });

  it("lists open jobs before closed ones", async () => {
    mount(TECH);
    await userEvent.click(screen.getByRole("combobox", { name: /based on job/i }));
    const options = (await screen.findAllByRole("option")).map((o) => o.textContent);
    expect(options).toEqual(["No job", "Data Scientist", "Old role"]);
  });

  it("shows a toast and keeps the rows when suggestion fails", async () => {
    mount(TECH, {}, () => HttpResponse.json({ detail: "job not found" }, { status: 404 }) as Response);
    await userEvent.click(suggestButton());
    expect(await screen.findByText("Couldn't suggest questions — try again.")).toBeInTheDocument();
    expect(questionTexts()).toEqual(["Q1"]);
  });
});

describe("InterviewTemplateSheet — a suggestion still in flight", () => {
  it("is dropped when the sheet is reopened on another template", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => { release = r; });
    server.use(
      http.get("http://localhost:8000/api/jobs", () => HttpResponse.json(JOBS)),
      http.post("http://localhost:8000/api/interview-templates/suggest-questions", async () => {
        await gate;
        return HttpResponse.json({ questions: [{ text: "Late", criterion: null }] });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const OTHER: InterviewTemplate = { ...TECH, id: 5, name: "Technical — DevOps",
                                       questions: [{ id: "d1", text: "D1" }] };
    const ui = (template: InterviewTemplate, open: boolean) => (
      <QueryClientProvider client={qc}>
        <InterviewTemplateSheet template={template} open={open} onOpenChange={() => {}} />
        <Toaster />
      </QueryClientProvider>
    );
    const { rerender } = render(ui(TECH, true));
    await userEvent.click(suggestButton());
    rerender(ui(TECH, false));
    rerender(ui(OTHER, true));
    expect(suggestButton()).toHaveTextContent("Suggest questions");
    release();
    await new Promise((r) => setTimeout(r, 100));
    expect(questionTexts()).toEqual(["D1"]);
  });
});
