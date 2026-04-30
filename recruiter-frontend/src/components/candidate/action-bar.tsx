import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useApplicationMutations } from "@/hooks/use-application-mutations";
import type { ApplicationRead } from "@/hooks/use-job-applications";
import { NotifyWizard } from "@/components/notify/notify-wizard";
import { RejectDialog } from "./reject-dialog";

interface Props {
  application: ApplicationRead;
  candidateEmail?: string | null;
}

export function ActionBar({ application, candidateEmail }: Props) {
  const m = useApplicationMutations(application.id, application.job_id);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [notifyOpen, setNotifyOpen] = useState(false);

  const stage = application.stage;
  const canValidate = stage === "scored";
  const canUnvalidate = stage === "validated" && !application.invited_at;
  const canReject =
    stage !== "rejected" && stage !== "invited" && stage !== "scheduled";
  const canNotify = stage === "validated" && !!candidateEmail;

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
        <Button size="sm" onClick={() => setNotifyOpen(true)}>
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
      {canNotify && candidateEmail && (
        <NotifyWizard
          open={notifyOpen}
          onOpenChange={setNotifyOpen}
          applicationId={application.id}
          jobId={application.job_id}
          candidateEmail={candidateEmail}
        />
      )}
    </div>
  );
}
