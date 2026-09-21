import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import type { ApplicationRead } from "./use-job-applications";

interface PatchPayload {
  stage?:
    | "scored"
    | "validated"
    | "rejected"
    | "scheduled"
    | "interviewed"
    | "offer"
    | "hired";
  notes?: string;
  rejection_reason?: string;
  interview_template_id?: number | null;
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
        // Empty string explicitly clears any prior reason; non-empty
        // sets it. Stored as a first-class column, surfaced as a
        // banner on the detail page.
        rejection_reason: reason || "",
      }),
    unreject: () => patch.mutate({ stage: "scored" }),
    // `undefined` omits interview_template_id so the server applies the
    // job's default; a number or null is sent as an explicit choice.
    markScheduled: (templateId?: number | null) =>
      patch.mutate(templateId === undefined
        ? { stage: "scheduled" }
        : { stage: "scheduled", interview_template_id: templateId }),
    markInterviewed: () => patch.mutate({ stage: "interviewed" }),
    // Reopen an interviewed candidate for another round. Same PATCH as
    // markScheduled: the server distinguishes the two by the stage it is
    // leaving, and only bumps the round when leaving `interviewed`.
    reopenRound: (templateId?: number | null) =>
      patch.mutate(templateId === undefined
        ? { stage: "scheduled" }
        : { stage: "scheduled", interview_template_id: templateId }),
    extendOffer: () => patch.mutate({ stage: "offer" }),
    markHired: () => patch.mutate({ stage: "hired" }),
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
