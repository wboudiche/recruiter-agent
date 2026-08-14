import { Link } from "react-router-dom";
import { useDraggable } from "@dnd-kit/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { ScoreBadge } from "./score-badge";
import { TimeInStageBadge } from "@/components/time-in-stage-badge";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import type { Density } from "./kanban-density-toggle";
import type { ApplicationRead } from "@/hooks/use-job-applications";

interface Props {
  application: ApplicationRead;
  jobId?: number;
  candidateName?: string;
  draggable?: boolean;
  density?: Density;
  selected?: boolean;
  onShiftClick?: (id: number) => void;
}

export function CandidateCard({
  application,
  jobId,
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

  const qc = useQueryClient();
  const lastError = application.last_error ?? null;
  // Retry needs BOTH conditions. The re-enrich endpoint can leave a
  // failure event on an application that has already scored; the retry
  // endpoint rejects anything that is not EXTRACTING, so offering the
  // button there would only produce a 409.
  const canRetry = Boolean(lastError) && application.stage === "extracting";

  const retryMut = useMutation({
    mutationFn: () => api(`/api/applications/${application.id}/retry`, { method: "POST" }),
    onSuccess: () => {
      toast.success("Extraction restarted");
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "Retry failed");
    },
    onSettled: () => {
      if (jobId !== undefined) {
        qc.invalidateQueries({ queryKey: queryKeys.jobApplications(jobId) });
      }
    },
  });

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
          <span className="text-muted-foreground capitalize">
            {awaitingPaste ? "needs paste" : application.stage}
          </span>
          <TimeInStageBadge application={application} />
        </div>
        {!compact && awaitingPaste && (
          <Badge
            variant="outline"
            className="border-yellow-500 text-yellow-700 bg-yellow-50"
          >
            Needs profile
          </Badge>
        )}
        {!compact && !awaitingPaste && !lastError &&
          (application.stage === "extracting" || application.stage === "enriching") && (
          <Badge
            variant="outline"
            className="border-[hsl(var(--ed-amber)/0.4)] text-[hsl(var(--ed-amber))] gap-1.5"
          >
            <Spinner size={10} />
            {application.stage === "enriching"
              ? "Enriching profile…"
              : "Extracting profile…"}
          </Badge>
        )}
        {!compact && lastError && (
          <div className="space-y-1">
            <p
              className="text-xs text-destructive truncate"
              title={lastError}
            >
              ⚠ {lastError}
            </p>
            {canRetry && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={retryMut.isPending}
                onClick={(e) => {
                  // The whole card is a <Link>; without this the click
                  // navigates to the detail page instead of retrying.
                  e.preventDefault();
                  e.stopPropagation();
                  retryMut.mutate();
                }}
              >
                {retryMut.isPending ? "Retrying…" : "Retry"}
              </Button>
            )}
          </div>
        )}
      </Link>
    </Card>
  );
}
