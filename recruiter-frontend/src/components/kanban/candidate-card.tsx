import { Link } from "react-router-dom";
import { useDraggable } from "@dnd-kit/core";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { ScoreBadge } from "./score-badge";
import { TimeInStageBadge } from "@/components/time-in-stage-badge";
import type { ApplicationRead } from "@/hooks/use-job-applications";

interface Props {
  application: ApplicationRead;
  candidateName?: string;
  draggable?: boolean;
}

export function CandidateCard({
  application,
  candidateName,
  draggable = true,
}: Props) {
  const isDraggable = draggable && application.stage !== "extracting";
  const awaitingPaste = application.awaiting_paste;
  const { attributes, listeners, setNodeRef, transform, isDragging } =
    useDraggable({
      id: `app-${application.id}`,
      data: { applicationId: application.id, currentStage: application.stage },
      disabled: !isDraggable,
    });
  const style = transform
    ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` }
    : undefined;

  return (
    <Card
      ref={setNodeRef}
      style={style}
      className={`p-3 ${isDragging ? "opacity-50" : ""} ${isDraggable ? "cursor-grab" : ""} ${awaitingPaste ? "border-yellow-500 border-2" : ""}`}
      {...(isDraggable ? listeners : {})}
      {...(isDraggable ? attributes : {})}
    >
      <Link to={`/applications/${application.id}`} className="block space-y-1">
        <div className="flex items-center justify-between">
          <span className="font-medium text-sm">
            {candidateName ?? `Candidate #${application.candidate_id}`}
          </span>
          <ScoreBadge score={application.score} />
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted-foreground capitalize">{application.stage}</span>
          <TimeInStageBadge application={application} />
        </div>
        {awaitingPaste && (
          <Badge
            variant="outline"
            className="border-yellow-500 text-yellow-700 bg-yellow-50"
          >
            Needs profile
          </Badge>
        )}
      </Link>
    </Card>
  );
}
