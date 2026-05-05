import { Link } from "react-router-dom";
import { useDraggable } from "@dnd-kit/core";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { ScoreBadge } from "./score-badge";
import { TimeInStageBadge } from "@/components/time-in-stage-badge";
import type { Density } from "./kanban-density-toggle";
import type { ApplicationRead } from "@/hooks/use-job-applications";

interface Props {
  application: ApplicationRead;
  candidateName?: string;
  draggable?: boolean;
  density?: Density;
  selected?: boolean;
  onShiftClick?: (id: number) => void;
}

export function CandidateCard({
  application,
  candidateName,
  draggable = true,
  density = "comfortable",
  selected = false,
  onShiftClick,
}: Props) {
  const isDraggable = draggable && application.stage !== "extracting";
  const awaitingPaste = application.awaiting_paste;
  const compact = density === "compact";
  const { attributes, listeners, setNodeRef, transform, isDragging } =
    useDraggable({
      id: `app-${application.id}`,
      data: { applicationId: application.id, currentStage: application.stage },
      disabled: !isDraggable,
    });
  const style = transform
    ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` }
    : undefined;

  function handleClick(e: React.MouseEvent) {
    if (e.shiftKey && onShiftClick) {
      e.preventDefault();
      onShiftClick(application.id);
    }
  }

  return (
    <Card
      ref={setNodeRef}
      style={style}
      className={`${compact ? "p-1.5" : "p-3"} ${isDragging ? "opacity-50" : ""} ${isDraggable ? "cursor-grab" : ""} ${awaitingPaste ? "border-yellow-500 border-2" : ""}${selected ? " ring-2 ring-primary/50" : ""}`}
      {...(isDraggable ? listeners : {})}
      {...(isDraggable ? attributes : {})}
    >
      <Link
        to={`/applications/${application.id}`}
        onClick={handleClick}
        className="block space-y-1"
      >
        <div className="flex items-center justify-between">
          <span className={`font-medium ${compact ? "text-xs" : "text-sm"} truncate`}>
            {candidateName ?? `Candidate #${application.candidate_id}`}
          </span>
          <ScoreBadge score={application.score} />
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted-foreground capitalize">{application.stage}</span>
          <TimeInStageBadge application={application} />
        </div>
        {awaitingPaste && !compact && (
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
