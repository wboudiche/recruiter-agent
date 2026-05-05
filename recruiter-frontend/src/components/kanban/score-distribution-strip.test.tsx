import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { ScoreDistributionStrip } from "./score-distribution-strip";
import type { ApplicationRead } from "@/hooks/use-job-applications";

function mkApp(id: number, score: number | null, stage: ApplicationRead["stage"] = "scored"): ApplicationRead {
  return {
    id, job_id: 1, candidate_id: id, stage,
    score, score_breakdown: null, score_rationale: null, notes: null,
    validated_at: null, invited_at: null, scheduled_at: null, rejected_at: null,
    created_at: "2026-05-05T00:00:00Z", updated_at: "2026-05-05T00:00:00Z",
    awaiting_paste: false,
  };
}

describe("ScoreDistributionStrip", () => {
  it("renders one tick per scored application", () => {
    const { container } = render(
      <ScoreDistributionStrip applications={[mkApp(1, 80), mkApp(2, 65), mkApp(3, 45)]} />
    );
    expect(container.querySelectorAll("rect").length).toBe(3);
  });

  it("renders nothing when applications is empty", () => {
    const { container } = render(<ScoreDistributionStrip applications={[]} />);
    expect(container.querySelector("svg")).toBeNull();
  });

  it("has a tick for each score band color (red < 50, yellow 50-79, green >= 80)", () => {
    const { container } = render(
      <ScoreDistributionStrip applications={[mkApp(1, 90), mkApp(2, 60), mkApp(3, 30)]} />
    );
    // All rects use fill="currentColor" so the band is encoded in the
    // className (text-{green|yellow|red}-*); three distinct band classes.
    const classes = Array.from(container.querySelectorAll("rect")).map(
      (r) => r.getAttribute("class") ?? "",
    );
    expect(classes.some((c) => c.includes("text-green"))).toBe(true);
    expect(classes.some((c) => c.includes("text-yellow"))).toBe(true);
    expect(classes.some((c) => c.includes("text-red"))).toBe(true);
  });
});
