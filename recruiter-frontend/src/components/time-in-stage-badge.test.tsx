import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { TimeInStageBadge } from "./time-in-stage-badge";
import type { ApplicationRead } from "@/hooks/use-job-applications";

const NOW = new Date("2026-05-05T12:00:00Z").getTime();

function mkApp(daysAgo: number, stage: ApplicationRead["stage"] = "scored"): ApplicationRead {
  const ts = new Date(NOW - daysAgo * 86_400_000).toISOString();
  return {
    id: 1, job_id: 1, candidate_id: 1, stage,
    score: null, score_breakdown: null, score_rationale: null, notes: null,
    validated_at: null, invited_at: null, scheduled_at: null, rejected_at: null,
    created_at: ts, updated_at: ts, awaiting_paste: false,
  };
}

describe("TimeInStageBadge", () => {
  beforeEach(() => vi.useFakeTimers().setSystemTime(NOW));
  afterEach(() => vi.useRealTimers());

  it("renders fresh label with muted color under 7d", () => {
    render(<TimeInStageBadge application={mkApp(3)} />);
    const el = screen.getByText("3d");
    expect(el.className).toContain("text-muted-foreground");
  });

  it("renders warning color at 7-14d", () => {
    render(<TimeInStageBadge application={mkApp(10)} />);
    const el = screen.getByText("10d");
    expect(el.className).toContain("text-yellow-600");
  });

  it("renders critical color at >14d", () => {
    render(<TimeInStageBadge application={mkApp(20)} />);
    const el = screen.getByText("20d");
    expect(el.className).toContain("text-red-600");
  });
});
