import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useSettings } from "@/hooks/use-settings";
import { useSendNotification } from "@/hooks/use-notify";
import type { Slot } from "@/hooks/use-notify";
import { StepChannel } from "./step-channel";
import { StepSlots } from "./step-slots";
import { StepDraft } from "./step-draft";
import { StepConfirm } from "./step-confirm";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  applicationId: number;
  jobId?: number;
  candidateEmail: string;
}

const STEPS = ["Channel", "Slots", "Draft", "Confirm"] as const;

export function NotifyWizard({
  open,
  onOpenChange,
  applicationId,
  jobId,
  candidateEmail,
}: Props) {
  const settings = useSettings();
  const send = useSendNotification(applicationId, jobId);
  const [step, setStep] = useState(0);
  const [channel, setChannel] = useState<"smtp" | "gmail">("smtp");
  const [slots, setSlots] = useState<Slot[]>([]);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");

  const hasSmtp = settings.data?.has_smtp_config ?? false;
  const hasGoogle = settings.data?.has_google_oauth_tokens ?? false;

  function reset() {
    setStep(0);
    setChannel("smtp");
    setSlots([]);
    setSubject("");
    setBody("");
  }

  function next() {
    if (step < STEPS.length - 1) setStep(step + 1);
  }
  function back() {
    if (step > 0) setStep(step - 1);
  }

  function canAdvance() {
    if (step === 0)
      return (channel === "smtp" && hasSmtp) || (channel === "gmail" && hasGoogle);
    if (step === 1) return slots.length >= 1;
    if (step === 2) return subject.trim().length > 0 && body.trim().length > 0;
    return true;
  }

  async function confirm() {
    await send.mutateAsync({ channel, subject, body, slots });
    reset();
    onOpenChange(false);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) reset();
        onOpenChange(o);
      }}
    >
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col gap-0 overflow-hidden">
        <DialogHeader className="shrink-0 pb-4 border-b">
          <DialogTitle>
            Notify & invite — Step {step + 1} of {STEPS.length}: {STEPS[step]}
          </DialogTitle>
        </DialogHeader>
        <div className="flex-1 overflow-y-auto py-4 -mr-2 pr-2">
          {step === 0 && (
            <StepChannel
              value={channel}
              onChange={setChannel}
              hasSmtpConfig={hasSmtp}
              hasGoogleOauth={hasGoogle}
            />
          )}
          {step === 1 && <StepSlots slots={slots} onChange={setSlots} />}
          {step === 2 && (
            <StepDraft
              applicationId={applicationId}
              slots={slots}
              subject={subject}
              body={body}
              onChange={(s, b) => {
                setSubject(s);
                setBody(b);
              }}
            />
          )}
          {step === 3 && (
            <StepConfirm
              channel={channel}
              candidateEmail={candidateEmail}
              subject={subject}
              body={body}
              slots={slots}
            />
          )}
        </div>
        <DialogFooter className="shrink-0 pt-4 border-t">
          {step > 0 && (
            <Button variant="outline" onClick={back} disabled={send.isPending}>
              Back
            </Button>
          )}
          {step < STEPS.length - 1 ? (
            <Button onClick={next} disabled={!canAdvance()}>
              Next
            </Button>
          ) : (
            <Button onClick={confirm} disabled={send.isPending}>
              {send.isPending ? "Sending…" : "Send"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
