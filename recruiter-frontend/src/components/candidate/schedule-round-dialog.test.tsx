import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ScheduleRoundDialog } from "./schedule-round-dialog";

const T = (id: number, name: string) => ({
  id, name, description: null, questions: [], probe_mode: "none" as const,
  include_job_questions: false, is_active: true,
});

describe("ScheduleRoundDialog", () => {
  it("preselects the job's default and confirms it", async () => {
    const onConfirm = vi.fn();
    render(<ScheduleRoundDialog open onOpenChange={() => {}} title="Schedule interview"
      templates={[T(1, "Technical"), T(2, "RH screen")]} defaultTemplateId={2}
      onConfirm={onConfirm} />);

    expect(screen.getByRole("combobox")).toHaveTextContent("RH screen");
    await userEvent.click(screen.getByRole("button", { name: /^schedule$/i }));
    expect(onConfirm).toHaveBeenCalledWith(2);
  });

  it("offers No template, confirmed as null", async () => {
    const onConfirm = vi.fn();
    render(<ScheduleRoundDialog open onOpenChange={() => {}} title="Schedule interview"
      templates={[T(1, "Technical")]} defaultTemplateId={null} onConfirm={onConfirm} />);

    expect(screen.getByRole("combobox")).toHaveTextContent(/no template/i);
    await userEvent.click(screen.getByRole("button", { name: /^schedule$/i }));
    expect(onConfirm).toHaveBeenCalledWith(null);
  });

  it("does not preselect a default that is not among the active templates", () => {
    render(<ScheduleRoundDialog open onOpenChange={() => {}} title="Schedule interview"
      templates={[T(1, "Technical")]} defaultTemplateId={99} onConfirm={() => {}} />);
    expect(screen.getByRole("combobox")).toHaveTextContent(/no template/i);
  });
});
