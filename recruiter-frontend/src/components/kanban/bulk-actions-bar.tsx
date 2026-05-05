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
  onClear: () => void;
}

async function patchOne(id: number, stage: "validated" | "rejected"): Promise<number> {
  await api(`/api/applications/${id}`, { method: "PATCH", json: { stage } });
  return id;
}

export function BulkActionsBar({ selected, applications, jobId, onClear }: Props) {
  const qc = useQueryClient();

  const validateMut = useMutation({
    mutationFn: async () => {
      return Promise.allSettled(
        [...selected].map((id) => patchOne(id, "validated"))
      );
    },
    onSettled: (results) => {
      qc.invalidateQueries({ queryKey: queryKeys.jobApplications(jobId) });
      const failures = (results ?? []).filter((r) => r.status === "rejected");
      if (failures.length === 0) {
        toast.success(`Validated ${selected.size} application${selected.size === 1 ? "" : "s"}`);
        onClear();
      } else {
        for (const r of failures) {
          if (r.status === "rejected") {
            const detail = r.reason instanceof ApiError ? r.reason.detail : "Validate failed";
            toast.error(detail);
          }
        }
      }
    },
  });

  const rejectMut = useMutation({
    mutationFn: async () => {
      return Promise.allSettled(
        [...selected].map((id) => patchOne(id, "rejected"))
      );
    },
    onSettled: (results) => {
      qc.invalidateQueries({ queryKey: queryKeys.jobApplications(jobId) });
      const failures = (results ?? []).filter((r) => r.status === "rejected");
      if (failures.length === 0) {
        toast.success(`Rejected ${selected.size} application${selected.size === 1 ? "" : "s"}`);
        onClear();
      } else {
        for (const r of failures) {
          if (r.status === "rejected") {
            const detail = r.reason instanceof ApiError ? r.reason.detail : "Reject failed";
            toast.error(detail);
          }
        }
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
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 bg-background border shadow-lg rounded-full px-4 py-2 text-sm">
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
      <Button size="sm" variant="ghost" onClick={onClear} disabled={pending}>
        Clear
      </Button>
    </div>
  );
}
