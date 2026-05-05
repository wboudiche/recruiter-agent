import { relativeTimeInStage } from "@/lib/time";
import type { ApplicationRead } from "@/hooks/use-job-applications";

const COLOR: Record<"fresh" | "warning" | "critical", string> = {
  fresh: "text-muted-foreground",
  warning: "text-yellow-600",
  critical: "text-red-600",
};

interface Props {
  application: ApplicationRead;
}

export function TimeInStageBadge({ application }: Props) {
  const { label, ageingLevel } = relativeTimeInStage(application);
  return (
    <span className={`text-[10px] tabular-nums ${COLOR[ageingLevel]}`}>
      {label}
    </span>
  );
}
