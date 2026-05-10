import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import type { ApplicationRead } from "./use-job-applications";

interface PatchPayload {
  stage?: "scored" | "validated" | "rejected";
  notes?: string;
}

export function useApplicationMutations(applicationId: number, jobId?: number) {
  const queryClient = useQueryClient();

  const patch = useMutation({
    mutationFn: (payload: PatchPayload) =>
      api<ApplicationRead>(`/api/applications/${applicationId}`, {
        method: "PATCH",
        json: payload,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.application(applicationId), data);
      if (jobId !== undefined) {
        queryClient.invalidateQueries({
          queryKey: queryKeys.jobApplications(jobId),
        });
      }
    },
    onError: (err) => {
      const detail = err instanceof ApiError ? err.detail : "Failed to update";
      toast.error(detail);
    },
  });

  return {
    validate: () => patch.mutate({ stage: "validated" }),
    unvalidate: () => patch.mutate({ stage: "scored" }),
    reject: (reason: string) =>
      patch.mutate({
        stage: "rejected",
        notes: reason ? `[REJECTED] ${reason}` : undefined,
      }),
    isPending: patch.isPending,
  };
}

export function useReEnrich() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (applicationId: number) =>
      api(`/api/applications/${applicationId}/re-enrich`, { method: "POST" }),
    onSuccess: (_, applicationId) => {
      qc.invalidateQueries({ queryKey: queryKeys.application(applicationId) });
      toast.success("Re-enrichment queued");
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Failed"),
  });
}
