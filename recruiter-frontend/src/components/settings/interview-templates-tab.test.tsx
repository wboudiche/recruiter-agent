import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { InterviewTemplatesTab } from "./interview-templates-tab";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// An RH screen as one is actually set up: history probes, the job's own
// technical questions left out.
const RH = { id: 3, name: "RH screen", description: null, questions: [],
             probe_mode: "profile", include_job_questions: false, is_active: true };

function mount(templates: unknown[], capture: { body?: any; path?: string } = {}) {
  server.use(
    http.get("http://localhost:8000/api/interview-templates", () => HttpResponse.json(templates)),
    http.post("http://localhost:8000/api/interview-templates", async ({ request }) => {
      capture.body = await request.json();
      return HttpResponse.json({ ...RH, id: 9, ...capture.body }, { status: 201 });
    }),
    http.patch("http://localhost:8000/api/interview-templates/:id", async ({ request, params }) => {
      capture.body = await request.json();
      capture.path = String(params.id);
      return HttpResponse.json({ ...RH, ...capture.body });
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><InterviewTemplatesTab /></QueryClientProvider>);
}

describe("InterviewTemplatesTab", () => {
  it("lists templates with what each one does", async () => {
    mount([RH]);
    await waitFor(() => expect(screen.getByText("RH screen")).toBeInTheDocument());
    expect(screen.getByText("HR")).toBeInTheDocument();
    expect(screen.getByText(/career history/i)).toBeInTheDocument();
  });

  it("creates an HR interview without asking about question sources", async () => {
    const capture: { body?: any } = {};
    mount([], capture);
    await userEvent.click(await screen.findByRole("button", { name: /new template/i }));
    await userEvent.type(screen.getByLabelText(/^name$/i), "RH screen");
    await userEvent.click(screen.getByRole("radio", { name: /^hr$/i }));
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    // The kind is the only thing chosen; both settings follow from it.
    await waitFor(() => expect(capture.body?.probe_mode).toBe("profile"));
    expect(capture.body.include_job_questions).toBe(false);
  });

  it("says in words what the chosen kind will do", async () => {
    mount([]);
    await userEvent.click(await screen.findByRole("button", { name: /new template/i }));
    expect(screen.getByText(/scorecard gaps/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: /^hr$/i }));
    expect(screen.getByText(/career history/i)).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /generated probes/i })).not.toBeInTheDocument();
  });

  it("keeps the underlying controls for a mix that is neither preset", async () => {
    const capture: { body?: any } = {};
    mount([], capture);
    await userEvent.click(await screen.findByRole("button", { name: /new template/i }));
    await userEvent.type(screen.getByLabelText(/^name$/i), "Curated");
    await userEvent.click(screen.getByRole("radio", { name: /^custom$/i }));
    await userEvent.click(screen.getByRole("combobox", { name: /generated probes/i }));
    await userEvent.click(await screen.findByRole("option", { name: /^none/i }));
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(capture.body?.probe_mode).toBe("none"));
  });

  it("opens an existing template on the kind it already is", async () => {
    mount([{ ...RH, probe_mode: "profile", include_job_questions: false }]);
    await userEvent.click(await screen.findByRole("button", { name: /edit rh screen/i }));
    expect(screen.getByRole("radio", { name: /^hr$/i })).toBeChecked();
  });

  it("names each template's kind in the list", async () => {
    mount([
      { ...RH, id: 1, name: "RH screen", probe_mode: "profile", include_job_questions: false },
      { ...RH, id: 2, name: "Deep dive", probe_mode: "score_gaps", include_job_questions: true },
      { ...RH, id: 3, name: "Curated", probe_mode: "none", include_job_questions: false },
    ]);
    await waitFor(() => expect(screen.getByText("RH screen")).toBeInTheDocument());
    expect(screen.getByText("HR")).toBeInTheDocument();
    expect(screen.getByText("Technical")).toBeInTheDocument();
    expect(screen.getByText("Custom")).toBeInTheDocument();
  });

  it("describes what a custom template does, not that it is custom", async () => {
    mount([{ ...RH, id: 4, name: "Curated", probe_mode: "none", include_job_questions: true }]);
    await waitFor(() => expect(screen.getByText("Curated")).toBeInTheDocument());

    expect(screen.getByText(/no generated questions/i)).toBeInTheDocument();
    expect(screen.getByText(/job's own questions are included/i)).toBeInTheDocument();
  });

  it("saves the job-questions setting a custom template unticks", async () => {
    const capture: { body?: any } = {};
    mount([], capture);
    await userEvent.click(await screen.findByRole("button", { name: /new template/i }));
    await userEvent.type(screen.getByLabelText(/^name$/i), "Curated");
    await userEvent.click(screen.getByRole("radio", { name: /^custom$/i }));
    await userEvent.click(screen.getByRole("checkbox", { name: /include the job's own/i }));
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(capture.body?.include_job_questions).toBe(false));
    expect(capture.body.probe_mode).toBe("score_gaps");
  });

  it("creates a template", async () => {
    const capture: { body?: any } = {};
    mount([], capture);
    await userEvent.click(await screen.findByRole("button", { name: /new template/i }));
    await userEvent.type(screen.getByLabelText(/^name$/i), "Technical");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(capture.body?.name).toBe("Technical"));
    expect(capture.body.probe_mode).toBe("score_gaps");
    expect(capture.body.include_job_questions).toBe(true);
  });

  it("trims a name typed with trailing spaces before saving", async () => {
    const capture: { body?: any } = {};
    mount([], capture);
    await userEvent.click(await screen.findByRole("button", { name: /new template/i }));
    await userEvent.type(screen.getByLabelText(/^name$/i), "RH screen  ");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(capture.body?.name).toBe("RH screen"));
  });

  it("edits a template", async () => {
    const capture: { body?: any; path?: string } = {};
    mount([RH], capture);
    await userEvent.click(await screen.findByRole("button", { name: /edit rh screen/i }));
    const name = screen.getByLabelText(/^name$/i);
    await userEvent.clear(name);
    await userEvent.type(name, "RH interview");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(capture.body?.name).toBe("RH interview"));
    expect(capture.path).toBe("3");
  });

  it("archives a template", async () => {
    const capture: { body?: any; path?: string } = {};
    mount([RH], capture);
    await userEvent.click(await screen.findByRole("button", { name: /archive rh screen/i }));
    await waitFor(() => expect(capture.body).toEqual({ is_active: false }));
    expect(capture.path).toBe("3");
  });
});
