import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useApplicationMutations } from "@/hooks/use-application-mutations";
import { useInterviewTemplates } from "@/hooks/use-interview-templates";
import { useJob } from "@/hooks/use-job";
import type { ApplicationRead } from "@/hooks/use-job-applications";
import { NotifyWizard } from "@/components/notify/notify-wizard";
import { RejectDialog } from "./reject-dialog";
import { ScheduleRoundDialog } from "./schedule-round-dialog";

interface Props {
  application: ApplicationRead;
  candidateEmail?: string | null;
}

export function ActionBar({ application, candidateEmail }: Props) {
  const m = useApplicationMutations(application.id, application.job_id);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [notifyOpen, setNotifyOpen] = useState(false);
  const templates = useInterviewTemplates(false).data ?? [];
  const job = useJob(application.job_id);
  const [pickerFor, setPickerFor] = useState<"schedule" | "reopen" | null>(null);

  // With no templates the picker would offer only "No template", so skip
  // it: one click, exactly as before templates existed. A click before the
  // list has loaded also lands here, and omitting the field makes the
  // server use the job's default, which is the safe choice.
  const startSchedule = () =>
    templates.length === 0 ? m.markScheduled() : setPickerFor("schedule");
  const startReopen = () =>
    templates.length === 0 ? m.reopenRound() : setPickerFor("reopen");

  const stage = application.stage;
  const canValidate = stage === "scored";
  const canUnvalidate = stage === "validated" && !application.invited_at;
  const canReject = stage !== "rejected" && stage !== "hired";
  const canNotify = stage === "validated" && !!candidateEmail;
  const canMarkScheduled = stage === "invited";
  const canMarkInterviewed = stage === "scheduled";
  const canExtendOffer = stage === "interviewed";
  const canReopenRound = stage === "interviewed";
  const canMarkHired = stage === "offer";

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
      {canMarkScheduled && (
        <Button size="sm" onClick={startSchedule} disabled={m.isPending}>
          Mark as scheduled
        </Button>
      )}
      {canMarkInterviewed && (
        <Button size="sm" onClick={m.markInterviewed} disabled={m.isPending}>
          Mark as interviewed
        </Button>
      )}
      {canExtendOffer && (
        <Button size="sm" onClick={m.extendOffer} disabled={m.isPending}>
          Extend offer
        </Button>
      )}
      {canReopenRound && (
        <Button
          size="sm"
          variant="outline"
          onClick={startReopen}
          disabled={m.isPending}
        >
          Another round
        </Button>
      )}
      {canMarkHired && (
        <Button size="sm" onClick={m.markHired} disabled={m.isPending}>
          Mark as hired
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
      <ScheduleRoundDialog
        open={pickerFor !== null}
        onOpenChange={(o) => { if (!o) setPickerFor(null); }}
        title={pickerFor === "reopen" ? "Start another round" : "Schedule interview"}
        templates={templates}
        defaultTemplateId={job.data?.default_interview_template_id ?? null}
        pending={m.isPending}
        onConfirm={(templateId) => {
          if (pickerFor === "reopen") m.reopenRound(templateId); else m.markScheduled(templateId);
          setPickerFor(null);
        }}
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
