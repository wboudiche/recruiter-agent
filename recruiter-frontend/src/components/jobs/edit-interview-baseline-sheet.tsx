import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { readOnlyNotice } from "@/lib/read-only-notice";

export interface BaselineQuestion {
  id: string;
  text: string;
  criterion?: string | null;
}

interface Props {
  jobId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  canWrite?: boolean;
}

// A bare `Date.now()` collides when two rows are added within the same
// millisecond, and the rows then track each other's edits (they share an
// id). Prefer the collision-proof `crypto.randomUUID()`; fall back to a
// monotonic counter appended to the timestamp where it isn't available.
let baselineIdCounter = 0;

function newBaselineId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  baselineIdCounter += 1;
  return `b-${Date.now()}-${baselineIdCounter}`;
}

export function EditInterviewBaselineSheet({
  jobId,
  open,
  onOpenChange,
  canWrite = false,
}: Props) {
  const qc = useQueryClient();
  const job = useQuery({
    queryKey: queryKeys.job(jobId),
    queryFn: () => api<{ interview_baseline: BaselineQuestion[] | null }>(`/api/jobs/${jobId}`),
  });
  // Editable working copy of the baseline. Reset from the job whenever the
  // sheet opens, so a cancelled edit never leaks into the next open.
  const [rows, setRows] = useState<BaselineQuestion[]>([]);

  useEffect(() => {
    if (open && job.data) setRows(job.data.interview_baseline ?? []);
  }, [open, job.data]);

  const save = useMutation({
    mutationFn: (questions: BaselineQuestion[]) =>
      api(`/api/jobs/${jobId}/interview-baseline`, {
        method: "PUT",
        json: { questions },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.job(jobId) });
      toast.success("Baseline questions saved");
      onOpenChange(false);
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "Couldn't save baseline questions");
    },
  });

  function update(i: number, text: string) {
    setRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, text } : r)));
  }
  function remove(i: number) {
    setRows((rs) => rs.filter((_, idx) => idx !== i));
  }
  function add() {
    setRows((rs) => [...rs, { id: newBaselineId(), text: "" }]);
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-xl flex flex-col">
        <SheetHeader>
          <SheetTitle>
            {canWrite ? "Edit baseline questions" : "Baseline questions"}
          </SheetTitle>
          <SheetDescription>
            {canWrite
              ? "Asked of every candidate for this role. Editing these does not change interviews already generated."
              : `${readOnlyNotice("edit baseline questions")} Asked of every candidate for this role.`}
          </SheetDescription>
        </SheetHeader>

        {canWrite && (
          <div className="flex items-center gap-2 py-3 border-b">
            <Button type="button" variant="outline" size="sm" onClick={add}>
              <Plus className="h-4 w-4 mr-1" />
              Add question
            </Button>
          </div>
        )}

        <div className="flex-1 overflow-y-auto space-y-4 py-4">
          {rows.length === 0 && (
            <p className="text-sm text-muted-foreground italic">
              {canWrite ? (
                <>No baseline questions yet. Use <em>Add question</em> to start.</>
              ) : (
                "No baseline questions set for this job yet."
              )}
            </p>
          )}
          {rows.map((row, i) => (
            <div key={row.id} className="flex gap-2 items-end">
              <div className="flex-1 space-y-1">
                <Label htmlFor={`baseline-${row.id}`}>Baseline question {i + 1}</Label>
                <Input
                  id={`baseline-${row.id}`}
                  value={row.text}
                  onChange={(e) => update(i, e.target.value)}
                  readOnly={!canWrite}
                />
              </div>
              {canWrite && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  // Deliberately doesn't repeat "Baseline question N" — that
                  // substring is also how the input's own label reads, and
                  // any lookup that matches on it (e.g. a case-insensitive
                  // "baseline question" query) would otherwise resolve both
                  // the input and this button and pick whichever sorts last.
                  aria-label={`Remove question ${i + 1}`}
                  onClick={() => remove(i)}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </div>
          ))}
        </div>

        <div className="border-t pt-3 flex justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={save.isPending}
          >
            {canWrite ? "Cancel" : "Close"}
          </Button>
          {canWrite && (
            <Button
              type="button"
              // Blank rows are dropped rather than rejected: an empty row is
              // an abandoned edit, not an error worth blocking a save for.
              onClick={() => save.mutate(rows.filter((r) => r.text.trim()))}
              disabled={save.isPending}
            >
              {save.isPending ? "Saving…" : "Save"}
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
