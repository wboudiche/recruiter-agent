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

const RH = { id: 3, name: "RH screen", description: null, questions: [],
             probe_mode: "none", include_job_questions: false, is_active: true };

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
    expect(screen.getByText(/no generated probes/i)).toBeInTheDocument();
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
