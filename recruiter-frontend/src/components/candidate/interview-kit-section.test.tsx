import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { InterviewKitSection } from "./interview-kit-section";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function mountWithKit(kit: unknown, capture: { body?: any } = {}) {
  server.use(
    http.get("http://localhost:8000/api/applications/1/interview-kit", () =>
      HttpResponse.json({ kit }),
    ),
    http.patch("http://localhost:8000/api/applications/1/interview-kit", async ({ request }) => {
      capture.body = await request.json();
      return HttpResponse.json({ kit });
    }),
    http.post("http://localhost:8000/api/applications/1/interview-kit/generate", () =>
      HttpResponse.json({ application_id: 1 }, { status: 202 }),
    ),
  );
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return render(<Wrapper><InterviewKitSection applicationId={1} canWrite /></Wrapper>);
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

  it("saves a typed answer", async () => {
    const cap: { body?: any } = {};
    mountWithKit(READY, cap);
    await waitFor(() => expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());

    await userEvent.type(screen.getAllByPlaceholderText(/what they said/i)[0], "Wants scale");
    await userEvent.click(screen.getByRole("button", { name: /save answers/i }));

    await waitFor(() => expect(cap.body).toBeDefined());
    expect(cap.body.questions[0].answer).toBe("Wants scale");
  });

  it("adds a question and includes it when saving", async () => {
    const cap: { body?: any } = {};
    mountWithKit(READY, cap);
    await waitFor(() => expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: /add question/i }));
    const inputs = screen.getAllByLabelText(/^Question:/i);
    await userEvent.type(inputs[inputs.length - 1], "Anything to ask us?");
    await userEvent.click(screen.getByRole("button", { name: /save answers/i }));

    await waitFor(() => expect(cap.body).toBeDefined());
    expect(cap.body.questions.map((q: any) => q.text)).toContain("Anything to ask us?");
  });

  it("removes a question", async () => {
    const cap: { body?: any } = {};
    mountWithKit(READY, cap);
    await waitFor(() => expect(screen.getByDisplayValue("Why this role?")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: /remove question: why this role/i }));
    await userEvent.click(screen.getByRole("button", { name: /save answers/i }));

    await waitFor(() => expect(cap.body).toBeDefined());
    expect(cap.body.questions.map((q: any) => q.text)).not.toContain("Why this role?");
  });

  it("hides every write control for a viewer", async () => {
    server.use(
      http.get("http://localhost:8000/api/applications/1/interview-kit", () =>
        HttpResponse.json({ kit: READY }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <InterviewKitSection applicationId={1} canWrite={false} />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByText("Why this role?")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /save answers/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /submit interview/i })).not.toBeInTheDocument();
  });
});
