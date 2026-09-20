import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { FeedbackTable } from "./feedback-table";

const Q = [
  { id: "q1", text: "Why?", source: "probe" as const, answer: null, rating: null },
  { id: "q2", text: "How?", source: "probe" as const, answer: null, rating: null },
];
const S = [
  { user_id: 1, name: "Ann", email: "ann@acme.com", submitted_at: "2026-09-14T10:00:00Z",
    sheet: { answers: { q1: { answer: "Fine", rating: "strong" as const } }, verdict: { decision: "hire" as const, note: null } } },
  { user_id: 2, name: null, email: "bob@acme.com", submitted_at: null,
    sheet: { answers: { q1: { answer: null, rating: "weak" as const } }, verdict: { decision: null, note: null } } },
];

describe("FeedbackTable", () => {
  it("renders one column per sheet with the verdict row on top", () => {
    render(<FeedbackTable questions={Q} sheets={S} />);
    expect(screen.getByRole("columnheader", { name: /Ann/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /bob@acme.com/ })).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveTextContent(/verdict/i);
    expect(rows[1]).toHaveTextContent(/hire/i);
  });

  it("shows ratings per question and hides unrated questions behind a toggle", async () => {
    render(<FeedbackTable questions={Q} sheets={S} />);
    expect(screen.getByRole("row", { name: /Why\?/ })).toHaveTextContent(/strong/);
    expect(screen.queryByRole("row", { name: /How\?/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /show 1 unrated/i }));
    expect(screen.getByRole("row", { name: /How\?/ })).toBeInTheDocument();
  });

});
