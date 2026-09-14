import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useInterviewers, useUserDirectory } from "@/hooks/use-interviewers";
import { ApiError } from "@/lib/api";

interface Props {
  applicationId: number;
  canWrite: boolean;
}

export function InterviewersPicker({ applicationId, canWrite }: Props) {
  const { interviewers, setInterviewers } = useInterviewers(applicationId);
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [checked, setChecked] = useState<number[]>([]);
  const directory = useUserDirectory(open);

  function openDialog() {
    setChecked(interviewers.map((i) => i.user_id));
    setFilter("");
    setOpen(true);
  }

  const visible = (directory.data ?? []).filter((u) => {
    const q = filter.trim().toLowerCase();
    return !q || u.email.toLowerCase().includes(q) || (u.name ?? "").toLowerCase().includes(q);
  });

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
        interviewers:
      </span>
      {interviewers.length === 0 && (
        <span className="text-sm text-muted-foreground">none</span>
      )}
      {interviewers.map((i) => (
        <span
          key={i.user_id}
          className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-xs"
        >
          {i.name ?? i.email}
          {i.submitted_at && <span aria-label="submitted" className="text-emerald-400">✓</span>}
        </span>
      ))}
      {canWrite && (
        <Button variant="outline" size="sm" className="h-auto px-2 py-1 text-xs" onClick={openDialog}>
          Assign
        </Button>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Assign interviewers</DialogTitle>
          </DialogHeader>
          <Input
            placeholder="Search by name or email"
            aria-label="Search users"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <ul className="max-h-72 space-y-1 overflow-y-auto">
            {visible.map((u) => {
              const label = u.name ? `${u.name} (${u.email})` : u.email;
              return (
                <li key={u.id}>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      aria-label={label}
                      checked={checked.includes(u.id)}
                      onChange={(e) =>
                        setChecked((ids) =>
                          e.target.checked ? [...ids, u.id] : ids.filter((x) => x !== u.id))}
                    />
                    {label}
                  </label>
                </li>
              );
            })}
          </ul>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button
              disabled={setInterviewers.isPending}
              onClick={() =>
                setInterviewers.mutate(checked, {
                  onSuccess: () => setOpen(false),
                  onError: (err) =>
                    toast.error(err instanceof ApiError ? err.detail : "Couldn't save interviewers"),
                })}
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
