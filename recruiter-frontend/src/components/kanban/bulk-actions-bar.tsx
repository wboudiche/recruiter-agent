import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import type { ApplicationRead } from "@/hooks/use-job-applications";

interface Props {
  selected: Set<number>;
  applications: ApplicationRead[];
  jobId: number;
  setSelected: (next: Set<number>) => void;
}

async function patchOne(id: number, stage: "validated" | "rejected"): Promise<number> {
  await api(`/api/applications/${id}`, { method: "PATCH", json: { stage } });
  return id;
}

interface RunArgs {
  selected: Set<number>;
  stage: "validated" | "rejected";
}

interface RunResult {
  failedIds: number[];
  failures: PromiseRejectedResult[];
}

async function runBulk({ selected, stage }: RunArgs): Promise<RunResult> {
  const ids = [...selected];
  const results = await Promise.allSettled(ids.map((id) => patchOne(id, stage)));
  const failedIds: number[] = [];
  const failures: PromiseRejectedResult[] = [];
  results.forEach((r, i) => {
    if (r.status === "rejected") {
      failedIds.push(ids[i]);
      failures.push(r);
    }
  });
  return { failedIds, failures };
}

export function BulkActionsBar({ selected, applications, jobId, setSelected }: Props) {
  const qc = useQueryClient();

  const validateMut = useMutation({
    mutationFn: () => runBulk({ selected, stage: "validated" }),
    onSettled: (res) => {
      qc.invalidateQueries({ queryKey: queryKeys.jobApplications(jobId) });
      if (!res) return;
      if (res.failedIds.length === 0) {
        toast.success(`Validated ${selected.size} application${selected.size === 1 ? "" : "s"}`);
        setSelected(new Set());
      } else {
        for (const f of res.failures) {
          const detail = f.reason instanceof ApiError ? f.reason.detail : "Validate failed";
          toast.error(detail);
        }
        // Narrow the selection to the ids that actually failed so the user
        // can retry only those.
        setSelected(new Set(res.failedIds));
      }
    },
  });

  const rejectMut = useMutation({
    mutationFn: () => runBulk({ selected, stage: "rejected" }),
    onSettled: (res) => {
      qc.invalidateQueries({ queryKey: queryKeys.jobApplications(jobId) });
      if (!res) return;
      if (res.failedIds.length === 0) {
        toast.success(`Rejected ${selected.size} application${selected.size === 1 ? "" : "s"}`);
        setSelected(new Set());
      } else {
        for (const f of res.failures) {
          const detail = f.reason instanceof ApiError ? f.reason.detail : "Reject failed";
          toast.error(detail);
        }
        setSelected(new Set(res.failedIds));
      }
    },
  });

  if (selected.size === 0) return null;

  // Validate is allowed only when all selected cards are in the Scored stage.
  const allValidatable = [...selected].every(
    (id) => applications.find((a) => a.id === id)?.stage === "scored"
  );

  const pending = validateMut.isPending || rejectMut.isPending;

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 flex items-center gap-3 bg-background border shadow-lg rounded-full px-4 py-2 text-sm">
      <span className="font-medium">{selected.size} selected</span>
      <Button
        size="sm"
        onClick={() => validateMut.mutate()}
        disabled={!allValidatable || pending}
      >
        Validate
      </Button>
      <Button
        size="sm"
        variant="destructive"
        onClick={() => {
          if (selected.size >= 3) {
            const ok = window.confirm(
              `Reject ${selected.size} applications? This cannot be undone via bulk action.`
            );
            if (!ok) return;
          }
          rejectMut.mutate();
        }}
        disabled={pending}
      >
        Reject
      </Button>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => setSelected(new Set())}
        disabled={pending}
      >
        Clear
      </Button>
    </div>
  );
}
