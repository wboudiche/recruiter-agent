import { useEffect, useRef } from "react";
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
  canWrite?: boolean;
}

export function CandidateCard({
  application,
  jobId,
  candidateName,
  draggable = true,
  density = "comfortable",
  selected = false,
  onShiftClick,
  canWrite = true,
}: Props) {
  const isDraggable = draggable && canWrite && application.stage !== "extracting";
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
  const lastErrorEventId = application.last_error_event_id ?? null;
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

  // `CandidateCard` is keyed by application id, so it does not remount
  // between pipeline runs and `retryMut.isSuccess` never resets on its
  // own. Capture which failure EVENT was showing when the user clicked;
  // once a different event id arrives we know the retried run reported
  // its own outcome, so it is safe to re-arm the button.
  //
  // Keyed on the event id, not the message: the likeliest retry outcome
  // is failing the same way, and a recurring rate limit / expired token /
  // missing model stringifies identically every time. Comparing text
  // would leave the button dead exactly when a second retry is needed.
  const clickedErrorEventRef = useRef<number | null>(null);
  const { isSuccess: retrySucceeded, reset: resetRetry } = retryMut;
  useEffect(() => {
    if (retrySucceeded && lastErrorEventId !== clickedErrorEventRef.current) {
      resetRetry();
    }
  }, [lastErrorEventId, retrySucceeded, resetRetry]);

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
            {canWrite && canRetry && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                // Stay disabled after a successful retry, not just while
                // in flight. The 202 response resolves in well under a
                // second, but `last_error` stays stale until the NEW
                // pipeline run writes its own event 10-60s later — so an
                // `isPending`-only guard re-enables the button on refetch
                // while the same stale error line is still showing.
                // Clicking again would start a second `process_application`
                // background task on the same application (double LLM
                // spend, duplicate scored events): the retry endpoint has
                // no idempotency guard and stage stays EXTRACTING, so every
                // repeat passes its 409 check.
                disabled={retryMut.isPending || retryMut.isSuccess}
                onClick={(e) => {
                  // The whole card is a <Link>; without this the click
                  // navigates to the detail page instead of retrying.
                  e.preventDefault();
                  e.stopPropagation();
                  clickedErrorEventRef.current = lastErrorEventId;
                  retryMut.mutate();
                }}
              >
                {retryMut.isPending || retryMut.isSuccess ? "Retrying…" : "Retry"}
              </Button>
            )}
          </div>
        )}
      </Link>
    </Card>
  );
}
