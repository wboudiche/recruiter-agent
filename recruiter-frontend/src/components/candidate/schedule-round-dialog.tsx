import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import type { InterviewTemplate } from "@/hooks/use-interview-templates";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** Active templates only. */
  templates: InterviewTemplate[];
  defaultTemplateId: number | null;
  onConfirm: (templateId: number | null) => void;
  pending?: boolean;
}

const NONE = "none";

export function ScheduleRoundDialog({
  open, onOpenChange, title, templates, defaultTemplateId, onConfirm, pending,
}: Props) {
  // A default that is archived or unknown is never preselected.
  const initial = templates.some((t) => t.id === defaultTemplateId)
    ? String(defaultTemplateId) : NONE;
  const [choice, setChoice] = useState(initial);
  useEffect(() => { if (open) setChoice(initial); }, [open, initial]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            The template decides which questions this round asks and whether any are generated.
          </DialogDescription>
        </DialogHeader>
        <Select value={choice} onValueChange={setChoice}>
          <SelectTrigger aria-label="Interview template"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE}>No template — the job's own questions</SelectItem>
            {templates.map((t) => (
              <SelectItem key={t.id} value={String(t.id)}>{t.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={pending}
            onClick={() => onConfirm(choice === NONE ? null : Number(choice))}>
            Schedule
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
