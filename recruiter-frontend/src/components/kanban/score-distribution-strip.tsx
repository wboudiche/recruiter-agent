import type { ApplicationRead } from "@/hooks/use-job-applications";

const STRIP_HEIGHT = 6;
const TICK_WIDTH = 2;

interface Props {
  applications: ApplicationRead[];
}

function colorForScore(score: number): string {
  if (score >= 80) return "#16a34a";   // green-600
  if (score >= 50) return "#ca8a04";   // yellow-600
  return "#dc2626";                    // red-600
}

export function ScoreDistributionStrip({ applications }: Props) {
  if (applications.length === 0) return null;
  return (
    <svg
      className="w-full"
      height={STRIP_HEIGHT}
      preserveAspectRatio="none"
      viewBox={`0 0 100 ${STRIP_HEIGHT}`}
      aria-label="score distribution"
    >
      {applications.map((app) => {
        const score = app.score ?? 0;
        const x = Math.max(0, Math.min(100 - TICK_WIDTH, score - TICK_WIDTH / 2));
        return (
          <rect
            key={app.id}
            x={x}
            y={0}
            width={TICK_WIDTH}
            height={STRIP_HEIGHT}
            fill={colorForScore(score)}
            opacity={app.score === null ? 0.5 : 1}
          >
            <title>{`Candidate #${app.candidate_id}: ${app.score ?? "—"}`}</title>
          </rect>
        );
      })}
    </svg>
  );
}
