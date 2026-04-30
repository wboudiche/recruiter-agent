import { screen } from "@testing-library/react";
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { render } from "../test/render";
import App from "@/App";

const server = setupServer(
  http.get("http://localhost:8000/api/jobs", () => HttpResponse.json([])),
);

describe("App", () => {
  beforeEach(() => server.listen({ onUnhandledRequest: "bypass" }));
  afterEach(() => {
    server.resetHandlers();
    server.close();
  });

  it("renders the app shell with header on /jobs", () => {
    render(<App noBrowserRouter />, { initialEntries: ["/jobs"] });
    expect(
      screen.getByRole("link", { name: /Recruiter Agent/i }),
    ).toBeInTheDocument();
  });

  it("redirects from / to /jobs", async () => {
    render(<App noBrowserRouter />, { initialEntries: ["/"] });
    expect(await screen.findByText(/No jobs yet/i)).toBeInTheDocument();
  });
});
