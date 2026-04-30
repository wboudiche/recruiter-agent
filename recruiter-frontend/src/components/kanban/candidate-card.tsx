import { Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { ScoreBadge } from "./score-badge";
import type { ApplicationRead } from "@/hooks/use-job-applications";

interface Props {
  application: ApplicationRead;
  candidateName?: string;
}

export function CandidateCard({ application, candidateName }: Props) {
  return (
    <Card className="p-3">
      <Link to={`/applications/${application.id}`} className="block space-y-1">
        <div className="flex items-center justify-between">
          <span className="font-medium text-sm">
            {candidateName ?? `Candidate #${application.candidate_id}`}
          </span>
          <ScoreBadge score={application.score} />
        </div>
        <p className="text-xs text-muted-foreground capitalize">{application.stage}</p>
      </Link>
    </Card>
  );
}
