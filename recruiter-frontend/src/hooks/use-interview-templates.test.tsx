import { describe, expect, it } from "vitest";
import { KIND_LABEL, KIND_SUMMARY, interviewKind, settingsForKind } from "./use-interview-templates";

describe("interviewKind", () => {
  it("names the two kinds a recruiter actually sets up", () => {
    expect(interviewKind({ probe_mode: "score_gaps", include_job_questions: true }))
      .toBe("technical");
    expect(interviewKind({ probe_mode: "profile", include_job_questions: false })).toBe("hr");
  });

  it("calls anything else custom rather than guessing", () => {
    // A technical source without the job's questions, or history probes
    // alongside them, is a deliberate mix — not one of the two presets.
    expect(interviewKind({ probe_mode: "score_gaps", include_job_questions: false }))
      .toBe("custom");
    expect(interviewKind({ probe_mode: "profile", include_job_questions: true })).toBe("custom");
    expect(interviewKind({ probe_mode: "none", include_job_questions: true })).toBe("custom");
    expect(interviewKind({ probe_mode: "none", include_job_questions: false })).toBe("custom");
  });

  it("round-trips the presets: what a kind sets is what it reads back as", () => {
    expect(interviewKind(settingsForKind("technical"))).toBe("technical");
    expect(interviewKind(settingsForKind("hr"))).toBe("hr");
  });

  it("has a label and a plain-language summary for each kind", () => {
    expect(KIND_LABEL.hr).toBe("HR");
    expect(KIND_SUMMARY.technical).toMatch(/scorecard/i);
    expect(KIND_SUMMARY.hr).toMatch(/history/i);
  });
});
