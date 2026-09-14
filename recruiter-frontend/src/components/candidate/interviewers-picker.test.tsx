import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
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

  it("shows a loading state then a no-match state in the assign dialog", async () => {
    mount(true);
    server.use(
      http.get("http://localhost:8000/api/users/directory", async () => {
        await delay(200);
        return HttpResponse.json([
          { id: 2, name: "Bob", email: "bob@acme.com", role: "viewer" },
          { id: 3, name: null, email: "carol@acme.com", role: "recruiter" },
        ]);
      }),
    );
    await userEvent.click(await screen.findByRole("button", { name: /assign/i }));
    expect(screen.getByText("Loading users…")).toBeInTheDocument();
    expect(await screen.findByRole("checkbox", { name: /carol@acme.com/ })).toBeInTheDocument();
    expect(screen.queryByText("Loading users…")).not.toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Search users"), "nobody-matches-this");
    expect(await screen.findByText("No users match.")).toBeInTheDocument();
  });

  // F2a: an early click, before the interviewers list itself has loaded,
  // used to seed `checked` from an empty array — the Assign dialog would
  // then open with every currently-assigned interviewer showing unchecked,
  // and hitting Save would unassign all of them.
  it("disables Assign until the interviewers list has loaded", async () => {
    server.use(
      http.get("http://localhost:8000/api/applications/1/interviewers", async () => {
        await delay(50);
        return HttpResponse.json([]);
      }),
      http.get("http://localhost:8000/api/users/directory", () => HttpResponse.json([])),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const Wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    render(<Wrapper><InterviewersPicker applicationId={1} canWrite /></Wrapper>);

    expect(screen.getByRole("button", { name: /assign/i })).toBeDisabled();
    await waitFor(() => expect(screen.getByRole("button", { name: /assign/i })).toBeEnabled());
  });

  // F2b: an interviewer whose account was deactivated (removed from the
  // user directory) must still show up in the Assign dialog so a writer
  // can untick them — otherwise there is no way to remove a deactivated
  // assignee from the panel at all.
  it("lets a writer unassign an interviewer no longer in the directory", async () => {
    const capture: { body?: any } = {};
    server.use(
      http.get("http://localhost:8000/api/applications/1/interviewers", () =>
        HttpResponse.json([
          { user_id: 2, name: "Bob", email: "bob@acme.com", submitted_at: null },
          { user_id: 9, name: null, email: "ghost@acme.com", submitted_at: null },
        ])),
      http.get("http://localhost:8000/api/users/directory", () =>
        HttpResponse.json([{ id: 2, name: "Bob", email: "bob@acme.com", role: "viewer" }])),
      http.put("http://localhost:8000/api/applications/1/interviewers", async ({ request }) => {
        capture.body = await request.json();
        return HttpResponse.json([]);
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const Wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    render(<Wrapper><InterviewersPicker applicationId={1} canWrite /></Wrapper>);

    await userEvent.click(await screen.findByRole("button", { name: /assign/i }));
    const ghost = await screen.findByRole("checkbox", { name: /ghost@acme.com/ });
    expect(ghost).toBeChecked();

    await userEvent.click(ghost);
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(capture.body).toEqual({ user_ids: [2] }));
  });
});
