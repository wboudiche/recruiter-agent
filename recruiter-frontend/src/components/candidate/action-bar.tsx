import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useApplicationMutations } from "@/hooks/use-application-mutations";
import type { ApplicationRead } from "@/hooks/use-job-applications";
import { RejectDialog } from "./reject-dialog";

interface Props {
  application: ApplicationRead;
}

export function ActionBar({ application }: Props) {
  const m = useApplicationMutations(application.id, application.job_id);
  const [rejectOpen, setRejectOpen] = useState(false);

  const stage = application.stage;
  const canValidate = stage === "scored";
  const canUnvalidate = stage === "validated" && !application.invited_at;
  const canReject =
    stage !== "rejected" && stage !== "invited" && stage !== "scheduled";
  const canNotify = stage === "validated";

  return (
    <div className="flex flex-wrap gap-2">
      {canValidate && (
        <Button size="sm" onClick={m.validate} disabled={m.isPending}>
          Validate
        </Button>
      )}
      {canUnvalidate && (
        <Button
          size="sm"
          variant="outline"
          onClick={m.unvalidate}
          disabled={m.isPending}
        >
          Unvalidate
        </Button>
      )}
      {canNotify && (
        <Button size="sm" onClick={() => toast.info("Notify wizard ships in Plan C")}>
          Notify & invite
        </Button>
      )}
      {canReject && (
        <Button
          size="sm"
          variant="destructive"
          onClick={() => setRejectOpen(true)}
          disabled={m.isPending}
        >
          Reject
        </Button>
      )}
      <RejectDialog
        open={rejectOpen}
        onOpenChange={setRejectOpen}
        onConfirm={m.reject}
      />
    </div>
  );
}
