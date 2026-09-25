import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  withKind,
  type InterviewTemplate,
} from "@/hooks/use-interview-templates";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** Active templates only. */
  templates: InterviewTemplate[];
  /** Ticked when the dialog opens: the job's default on first scheduling,
   *  the previous round's tracks on "Another round". Archived or unknown
   *  ids are dropped; if nothing is left, "No template" is ticked. */
  preselected: (number | null)[];
  /** The ticked choices — "No template" (null) first, then templates in
   *  list order, the order the round's tracks are created and shown in. */
  onConfirm: (templateIds: (number | null)[]) => void;
  pending?: boolean;
}

export function ScheduleRoundDialog({
  open, onOpenChange, title, templates, preselected, onConfirm, pending,
}: Props) {
  const activeIds = new Set(templates.map((t) => t.id));
  const kept = preselected.filter((id) => id === null || activeIds.has(id));
  // A string key, so a fresh-but-equal array each render does not re-run
  // the reset below and wipe what the user ticked.
  const initialKey = JSON.stringify(kept.length > 0 ? kept : [null]);
  const [chosen, setChosen] = useState<(number | null)[]>(() => JSON.parse(initialKey));
  useEffect(() => { if (open) setChosen(JSON.parse(initialKey)); }, [open, initialKey]);

  const options = [
    { id: null as number | null, label: "No template — the job's own questions" },
    ...templates.map((t) => ({
      id: t.id as number | null,
      label: withKind(t.name, t),
    })),
  ];
  const ordered = options.map((o) => o.id).filter((id) => chosen.includes(id));
  const toggle = (id: number | null, on: boolean) =>
    setChosen((c) => (on ? [...c, id] : c.filter((x) => x !== id)));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            Each ticked template becomes a track — its own questions, interviewers and
            sheets, run in parallel.
          </DialogDescription>
        </DialogHeader>
        <ul className="space-y-1">
          {options.map((o) => (
            <li key={o.id ?? "none"}>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={chosen.includes(o.id)}
                  onChange={(e) => toggle(o.id, e.target.checked)}
                />
                {o.label}
              </label>
            </li>
          ))}
        </ul>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={pending || ordered.length === 0} onClick={() => onConfirm(ordered)}>
            Schedule
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
