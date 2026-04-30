import { screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { render } from "../test/render";
import App from "@/App";

describe("App", () => {
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
