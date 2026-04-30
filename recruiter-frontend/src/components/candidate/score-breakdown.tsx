import { Card } from "@/components/ui/card";
import type { ApplicationRead } from "@/hooks/use-job-applications";

interface Props {
  application: ApplicationRead;
}

export function ScoreBreakdown({ application }: Props) {
  if (!application.score_breakdown?.length) {
    return <p className="text-sm text-muted-foreground">No score yet.</p>;
  }
  return (
    <Card className="p-4 space-y-3">
      <div className="flex items-baseline justify-between">
        <span className="text-2xl font-semibold">{application.score}</span>
        <span className="text-xs text-muted-foreground">overall</span>
      </div>
      <ul className="space-y-2">
        {application.score_breakdown.map((b) => (
          <li key={b.criterion} className="space-y-1">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium">{b.criterion}</span>
              <span className="text-muted-foreground">
                {b.score} · weight {b.weight.toFixed(2)}
              </span>
            </div>
            <div className="h-1.5 rounded bg-muted overflow-hidden">
              <div className="h-full bg-primary" style={{ width: `${b.score}%` }} />
            </div>
            <p className="text-xs text-muted-foreground">{b.rationale}</p>
          </li>
        ))}
      </ul>
      {application.score_rationale && (
        <p className="text-sm border-t pt-3">{application.score_rationale}</p>
      )}
    </Card>
  );
}
