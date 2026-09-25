import { describe, expect, it } from "vitest";
import {
  KIND_LABEL,
  KIND_SUMMARY,
  interviewKind,
  settingsForKind,
  settingsSummary,
  withKind,
} from "./use-interview-templates";

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

  it("hands out a copy of a preset, so a caller cannot rewrite the table", () => {
    // Every label in the app is derived by matching against PRESETS. A
    // caller building a variant from settingsForKind("hr") and editing it
    // would otherwise mutate the preset itself, and every real HR
    // template would silently start reading as "Custom".
    const settings = settingsForKind("hr");
    settings.include_job_questions = true;

    expect(settingsForKind("hr")).toEqual({ probe_mode: "profile", include_job_questions: false });
    expect(interviewKind({ probe_mode: "profile", include_job_questions: false })).toBe("hr");
  });
});

describe("settingsSummary", () => {
  it("reads back a preset's summary", () => {
    expect(settingsSummary({ probe_mode: "profile", include_job_questions: false }))
      .toBe(KIND_SUMMARY.hr);
  });

  it("spells out a mix that is neither preset, rather than calling it custom", () => {
    // "Set the question sources yourself" instructs the person choosing;
    // it describes nothing to someone reading a list of templates.
    const summary = settingsSummary({ probe_mode: "none", include_job_questions: true });
    expect(summary).toMatch(/no generated questions/i);
    expect(summary).toMatch(/job's own questions are included/i);
    expect(settingsSummary({ probe_mode: "score_gaps", include_job_questions: false }))
      .toMatch(/scorecard gaps/i);
  });
});

describe("withKind", () => {
  it("names a template with what it runs, the one way everywhere", () => {
    expect(withKind("RH screen", { probe_mode: "profile", include_job_questions: false }))
      .toBe("RH screen · HR");
  });
});
