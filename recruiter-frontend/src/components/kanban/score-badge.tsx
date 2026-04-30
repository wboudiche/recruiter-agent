import { cn } from "@/lib/utils";

interface Props {
  score: number | null;
}

export function ScoreBadge({ score }: Props) {
  if (score === null) return null;
  const tone =
    score >= 80
      ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
      : score >= 60
        ? "bg-amber-500/15 text-amber-700 dark:text-amber-400"
        : "bg-red-500/15 text-red-700 dark:text-red-400";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        tone,
      )}
    >
      {score}
    </span>
  );
}
