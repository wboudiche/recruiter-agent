import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { InterviewersPicker } from "./interviewers-picker";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function mount(canWrite: boolean, capture: { body?: any } = {}) {
  server.use(
    http.get("http://localhost:8000/api/applications/1/interviewers", () =>
      HttpResponse.json([{ user_id: 2, name: "Bob", email: "bob@acme.com", submitted_at: "2026-09-14T10:00:00Z" }])),
    http.get("http://localhost:8000/api/users/directory", () =>
      HttpResponse.json([
        { id: 2, name: "Bob", email: "bob@acme.com", role: "viewer" },
        { id: 3, name: null, email: "carol@acme.com", role: "recruiter" },
      ])),
    http.put("http://localhost:8000/api/applications/1/interviewers", async ({ request }) => {
      capture.body = await request.json();
      return HttpResponse.json([]);
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return render(<Wrapper><InterviewersPicker applicationId={1} canWrite={canWrite} /></Wrapper>);
}

describe("InterviewersPicker", () => {
  it("shows assigned interviewers with a submitted mark", async () => {
    mount(false);
    expect(await screen.findByText("Bob")).toBeInTheDocument();
    expect(screen.getByLabelText("submitted")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /assign/i })).not.toBeInTheDocument();
  });

  it("lets a writer reconcile the list", async () => {
    const capture: { body?: any } = {};
    mount(true, capture);
    await userEvent.click(await screen.findByRole("button", { name: /assign/i }));
    const carol = await screen.findByRole("checkbox", { name: /carol@acme.com/ });
    expect(screen.getByRole("checkbox", { name: /bob@acme.com/ })).toBeChecked();
    await userEvent.click(carol);
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(capture.body).toEqual({ user_ids: [2, 3] }));
  });
});
