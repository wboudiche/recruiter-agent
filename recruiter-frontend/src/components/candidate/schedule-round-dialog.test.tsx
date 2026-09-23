import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ScheduleRoundDialog } from "./schedule-round-dialog";

const T = (id: number, name: string) => ({
  id, name, description: null, questions: [], probe_mode: "none" as const,
  include_job_questions: false, is_active: true,
});

function mount(preselected: (number | null)[], onConfirm = vi.fn()) {
  render(<ScheduleRoundDialog open onOpenChange={() => {}} title="Schedule interview"
    templates={[T(1, "Technical"), T(2, "RH screen")]} preselected={preselected}
    onConfirm={onConfirm} />);
  return onConfirm;
}

describe("ScheduleRoundDialog", () => {
  it("preselects the given templates and confirms them", async () => {
    const onConfirm = mount([2]);
    expect(screen.getByRole("checkbox", { name: "RH screen" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Technical" })).not.toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: /^schedule$/i }));
    expect(onConfirm).toHaveBeenCalledWith([2]);
  });

  it("confirms several tracks, No template first, then list order", async () => {
    const onConfirm = mount([2]);
    await userEvent.click(screen.getByRole("checkbox", { name: "Technical" }));
    await userEvent.click(screen.getByRole("checkbox", { name: /no template/i }));
    await userEvent.click(screen.getByRole("button", { name: /^schedule$/i }));
    expect(onConfirm).toHaveBeenCalledWith([null, 1, 2]);
  });

  it("falls back to No template when the preselection is archived or unknown", () => {
    mount([99]);
    expect(screen.getByRole("checkbox", { name: /no template/i })).toBeChecked();
  });

  it("cannot schedule with nothing ticked", async () => {
    mount([1]);
    await userEvent.click(screen.getByRole("checkbox", { name: "Technical" }));
    expect(screen.getByRole("button", { name: /^schedule$/i })).toBeDisabled();
  });
});
