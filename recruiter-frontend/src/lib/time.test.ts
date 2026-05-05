import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { relativeTimeInStage } from "./time";
import type { ApplicationRead } from "@/hooks/use-job-applications";

const NOW = new Date("2026-05-05T12:00:00Z").getTime();

function mkApp(overrides: Partial<ApplicationRead>): ApplicationRead {
  return {
    id: 1, job_id: 1, candidate_id: 1, stage: "scored",
    score: 80, score_breakdown: null, score_rationale: null, notes: null,
    validated_at: null, invited_at: null, scheduled_at: null, rejected_at: null,
    created_at: new Date(NOW).toISOString(),
    updated_at: new Date(NOW).toISOString(),
    awaiting_paste: false,
    ...overrides,
  };
}

describe("relativeTimeInStage", () => {
  beforeEach(() => vi.useFakeTimers().setSystemTime(NOW));
  afterEach(() => vi.useRealTimers());

  it("renders <1m for under 5 minutes", () => {
    const app = mkApp({ created_at: new Date(NOW - 60_000).toISOString() });
    expect(relativeTimeInStage(app)).toEqual({
      label: "<1m", ageingLevel: "fresh",
    });
  });

  it("renders 5h for hours", () => {
    const app = mkApp({ created_at: new Date(NOW - 5 * 3600_000).toISOString() });
    expect(relativeTimeInStage(app).label).toBe("5h");
    expect(relativeTimeInStage(app).ageingLevel).toBe("fresh");
  });

  it("renders Nd for days, fresh < 7d", () => {
    const app = mkApp({ created_at: new Date(NOW - 3 * 86400_000).toISOString() });
    expect(relativeTimeInStage(app).label).toBe("3d");
    expect(relativeTimeInStage(app).ageingLevel).toBe("fresh");
  });

  it("flags warning at 7-14 days", () => {
    const app = mkApp({ created_at: new Date(NOW - 10 * 86400_000).toISOString() });
    expect(relativeTimeInStage(app).label).toBe("10d");
    expect(relativeTimeInStage(app).ageingLevel).toBe("warning");
  });

  it("flags critical at >14 days", () => {
    const app = mkApp({ created_at: new Date(NOW - 20 * 86400_000).toISOString() });
    expect(relativeTimeInStage(app).label).toBe("20d");
    expect(relativeTimeInStage(app).ageingLevel).toBe("critical");
  });

  it("uses validated_at for validated stage", () => {
    const app = mkApp({
      stage: "validated",
      created_at: new Date(NOW - 30 * 86400_000).toISOString(),
      validated_at: new Date(NOW - 2 * 86400_000).toISOString(),
    });
    // 2d since stage entry, not 30d since creation.
    expect(relativeTimeInStage(app).label).toBe("2d");
  });

  it("falls back to created_at when stage timestamp is null", () => {
    const app = mkApp({
      stage: "validated",
      created_at: new Date(NOW - 5 * 86400_000).toISOString(),
      validated_at: null,
    });
    expect(relativeTimeInStage(app).label).toBe("5d");
  });

  it("returns em-dash when all timestamps null", () => {
    const app = mkApp({
      stage: "extracting",
      created_at: null as unknown as string,
    });
    expect(relativeTimeInStage(app).label).toBe("—");
  });
});
