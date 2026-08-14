// recruiter-frontend/src/routes/login.test.tsx
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import Login from "./login";

const server = setupServer();

function renderLogin(nextParam: string) {
  return render(
    <MemoryRouter initialEntries={[`/login?next=${encodeURIComponent(nextParam)}`]}>
      <Login />
    </MemoryRouter>,
  );
}

async function submitPasswordForm() {
  await userEvent.type(screen.getByLabelText(/email/i), "recruiter@acme.com");
  await userEvent.type(screen.getByLabelText(/password/i), "s3cret");
  await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
}

describe("Login — post-password-login redirect", () => {
  let originalLocation: PropertyDescriptor | undefined;
  let setterCalls: string[];

  beforeEach(() => {
    server.listen({ onUnhandledRequest: "error" });
    server.use(
      http.get("http://localhost:8000/api/auth/methods", () =>
        HttpResponse.json({ oidc: false, password: true }),
      ),
      // Password login returns a bare 204 — no JSON body — so this page
      // cannot read a redirect back from the response. See safeNextPath.
      http.post("http://localhost:8000/api/auth/login/password", () =>
        new HttpResponse(null, { status: 204 }),
      ),
    );

    originalLocation = Object.getOwnPropertyDescriptor(window, "location");
    setterCalls = [];
    Object.defineProperty(window, "location", {
      value: {
        pathname: "/login",
        search: "",
        get href() {
          return "";
        },
        set href(v: string) {
          setterCalls.push(v);
        },
      },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    server.resetHandlers();
    server.close();
    if (originalLocation) {
      Object.defineProperty(window, "location", originalLocation);
    }
  });

  it("navigates to a same-origin `next` after a successful password login", async () => {
    renderLogin("/jobs/8");
    await screen.findByLabelText(/email/i);
    await submitPasswordForm();

    await waitFor(() => expect(setterCalls).toContain("/jobs/8"));
  });

  it("falls back to `/` for a protocol-relative (open-redirect) `next`", async () => {
    renderLogin("//evil.example");
    await screen.findByLabelText(/email/i);
    await submitPasswordForm();

    await waitFor(() => expect(setterCalls).toContain("/"));
    expect(setterCalls).not.toContain("//evil.example");
  });
});
