import type { ApplicationRead } from "@/hooks/use-job-applications";

const STRIP_HEIGHT = 6;
const TICK_WIDTH = 2;

interface Props {
  applications: ApplicationRead[];
}

// `fill="currentColor"` lets us drive the rect color from the rect's CSS color
// (the Tailwind `text-*` class), which gives us automatic dark-mode handling.
function classForScore(score: number): string {
  if (score >= 80) return "text-green-600 dark:text-green-500";
  if (score >= 50) return "text-yellow-600 dark:text-yellow-500";
  return "text-red-600 dark:text-red-500";
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
            fill="currentColor"
            className={classForScore(score)}
            opacity={app.score === null ? 0.5 : 1}
          >
            <title>{`Candidate #${app.candidate_id}: ${app.score ?? "—"}`}</title>
          </rect>
        );
      })}
    </svg>
  );
}
