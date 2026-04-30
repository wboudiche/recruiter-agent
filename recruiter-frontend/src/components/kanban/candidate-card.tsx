import { Link } from "react-router-dom";
import { useDraggable } from "@dnd-kit/core";
import { Card } from "@/components/ui/card";
import { ScoreBadge } from "./score-badge";
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
      className={`p-3 ${isDragging ? "opacity-50" : ""} ${isDraggable ? "cursor-grab" : ""}`}
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
        <p className="text-xs text-muted-foreground capitalize">
          {application.stage}
        </p>
      </Link>
    </Card>
  );
}
