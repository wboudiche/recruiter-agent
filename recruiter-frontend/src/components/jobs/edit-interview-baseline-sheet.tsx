import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { QuestionListEditor } from "@/components/interview/question-list-editor";
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

export function EditInterviewBaselineSheet({
  jobId,
  open,
  onOpenChange,
  canWrite = false,
}: Props) {
  const qc = useQueryClient();
  const job = useQuery({
    queryKey: queryKeys.job(jobId),
    queryFn: () =>
      api<{ interview_baseline: BaselineQuestion[] | null; updated_at?: string }>(
        `/api/jobs/${jobId}`,
      ),
  });
  // Editable working copy of the baseline. Reset from the job whenever the
  // sheet opens, so a cancelled edit never leaks into the next open.
  //
  // Deliberately keyed on `job.data?.updated_at`, not `job.data` itself:
  // handleServerEvent invalidates the whole `["jobs"]` query family on
  // every stage/error SSE event (any candidate, any job), which refetches
  // this job too. A refetch returns a new object identity even when
  // nothing about this job changed, so keying on `job.data` would wipe
  // unsaved rows on unrelated background traffic. `updated_at` only
  // changes when this job actually changed.
  const [rows, setRows] = useState<BaselineQuestion[]>([]);

  useEffect(() => {
    if (open && job.data) setRows(job.data.interview_baseline ?? []);
  }, [open, job.data?.updated_at]);

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

        <QuestionListEditor
          rows={rows}
          onChange={setRows}
          canWrite={canWrite}
          labelPrefix="Baseline question"
          idPrefix="baseline"
          emptyMessage={canWrite
            ? <>No baseline questions yet. Use <em>Add question</em> to start.</>
            : "No baseline questions set for this job yet."}
        />

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
