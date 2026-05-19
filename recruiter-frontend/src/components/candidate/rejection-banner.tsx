import { useState } from "react";
import { XCircle, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useApplicationMutations } from "@/hooks/use-application-mutations";
import type { ApplicationRead } from "@/hooks/use-job-applications";

interface Props {
  application: ApplicationRead;
}

/**
 * Banner shown above the score breakdown when stage=rejected. Surfaces
 * the structured `rejection_reason` and offers an Unreject affordance
 * (rejected → scored, allowed by the backend). Returns null otherwise.
 */
export function RejectionBanner({ application }: Props) {
  const m = useApplicationMutations(application.id, application.job_id);
  const [confirming, setConfirming] = useState(false);

  if (application.stage !== "rejected") return null;

  const when = application.rejected_at
    ? new Date(application.rejected_at).toLocaleString()
    : null;

  return (
    <div
      role="status"
      className="border border-[hsl(var(--destructive)/0.4)] bg-[hsl(var(--destructive)/0.06)] p-4 space-y-3"
    >
      <div className="flex items-start gap-3">
        <XCircle
          className="h-5 w-5 text-[hsl(var(--destructive))] mt-0.5 shrink-0"
          aria-hidden="true"
        />
        <div className="flex-1 min-w-0 space-y-1">
          <p className="text-[11px] uppercase tracking-[0.22em] text-[hsl(var(--destructive))]">
            Rejected{when ? ` · ${when}` : ""}
          </p>
          {application.rejection_reason ? (
            <p className="font-serif italic text-base leading-relaxed text-foreground">
              "{application.rejection_reason}"
            </p>
          ) : (
            <p className="text-sm text-muted-foreground italic">
              No reason was recorded.
            </p>
          )}
        </div>
      </div>
      <div className="flex justify-end">
        {confirming ? (
          <div className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground">
              Move back to Scored?
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setConfirming(false)}
              disabled={m.isPending}
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => {
                m.unreject();
                setConfirming(false);
              }}
              disabled={m.isPending}
            >
              Unreject
            </Button>
          </div>
        ) : (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setConfirming(true)}
          >
            <RotateCcw className="h-3.5 w-3.5 mr-1" />
            Unreject
          </Button>
        )}
      </div>
    </div>
  );
}
