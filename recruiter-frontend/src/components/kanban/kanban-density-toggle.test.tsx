import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { KanbanDensityToggle } from "./kanban-density-toggle";

describe("KanbanDensityToggle", () => {
  beforeEach(() => localStorage.clear());

  it("renders both options and reflects value", () => {
    const { rerender } = render(
      <KanbanDensityToggle value="comfortable" onChange={() => {}} />
    );
    const compact = screen.getByRole("button", { name: /compact/i });
    const comfortable = screen.getByRole("button", { name: /comfortable/i });
    // Selected state asserted via aria-pressed (not Tailwind classes).
    expect(comfortable.getAttribute("aria-pressed")).toBe("true");
    expect(compact.getAttribute("aria-pressed")).toBe("false");

    rerender(<KanbanDensityToggle value="compact" onChange={() => {}} />);
    expect(compact.getAttribute("aria-pressed")).toBe("true");
  });

  it("fires onChange when clicked", () => {
    let value: "comfortable" | "compact" = "comfortable";
    const { rerender } = render(
      <KanbanDensityToggle value={value} onChange={(v) => (value = v)} />
    );
    fireEvent.click(screen.getByRole("button", { name: /compact/i }));
    expect(value).toBe("compact");
    rerender(<KanbanDensityToggle value={value} onChange={(v) => (value = v)} />);
    expect(screen.getByRole("button", { name: /compact/i }).getAttribute("aria-pressed")).toBe("true");
  });
});
