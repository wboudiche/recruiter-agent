import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import type { JobRead } from "@/hooks/use-jobs";
import { EditJobDetailsSheet } from "./edit-job-details-sheet";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const JOB: JobRead = {
  id: 6, title: "Backend", description: "JD", criteria: [], status: "open",
  default_interview_template_id: null,
  created_at: "2026-09-21T00:00:00Z", updated_at: "2026-09-21T00:00:00Z",
};
const RH = { id: 3, name: "RH screen", description: null, questions: [],
             probe_mode: "none", include_job_questions: false, is_active: true };

function mount(job: JobRead, capture: { body?: any }) {
  server.use(
    http.get("http://localhost:8000/api/interview-templates", () => HttpResponse.json([RH])),
    http.patch("http://localhost:8000/api/jobs/6", async ({ request }) => {
      capture.body = await request.json();
      return HttpResponse.json({ ...job, ...capture.body });
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <EditJobDetailsSheet job={job} open onOpenChange={() => {}} canWrite />
    </QueryClientProvider>,
  );
}

describe("EditJobDetailsSheet — default interview template", () => {
  it("saves the chosen default", async () => {
    const capture: { body?: any } = {};
    mount(JOB, capture);

    await userEvent.click(
      await screen.findByRole("combobox", { name: /default interview template/i }));
    await userEvent.click(await screen.findByRole("option", { name: /rh screen/i }));
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(capture.body?.default_interview_template_id).toBe(3));
  });

  it("does not resend an untouched default, so an archived one cannot block a title save", async () => {
    // Job 6's default (template 99) has since been archived: it is not in
    // the active list. Re-sending it would make the server refuse the save.
    const capture: { body?: any } = {};
    mount({ ...JOB, default_interview_template_id: 99 }, capture);

    const title = await screen.findByLabelText(/^title$/i);
    await userEvent.clear(title);
    await userEvent.type(title, "Platform");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(capture.body?.title).toBe("Platform"));
    expect(capture.body).not.toHaveProperty("default_interview_template_id");
  });
});
