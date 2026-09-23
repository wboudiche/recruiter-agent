import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

export interface TrackOption {
  templateId: number | null;
  label: string;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Tracks this round does not have yet. */
  options: TrackOption[];
  onConfirm: (templateId: number | null) => void;
  pending?: boolean;
}

const NONE = "none";
const valueOf = (o: TrackOption) => (o.templateId === null ? NONE : String(o.templateId));

export function AddTrackDialog({ open, onOpenChange, options, onConfirm, pending }: Props) {
  const first = options[0] ? valueOf(options[0]) : "";
  const [choice, setChoice] = useState(first);
  useEffect(() => { if (open) setChoice(first); }, [open, first]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a track</DialogTitle>
          <DialogDescription>
            A parallel interview in this round, with its own questions, interviewers and sheets.
          </DialogDescription>
        </DialogHeader>
        <Select value={choice} onValueChange={setChoice}>
          <SelectTrigger aria-label="Track template"><SelectValue /></SelectTrigger>
          <SelectContent>
            {options.map((o) => (
              <SelectItem key={valueOf(o)} value={valueOf(o)}>{o.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={pending || !choice}
            onClick={() => onConfirm(choice === NONE ? null : Number(choice))}>
            Add track
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
