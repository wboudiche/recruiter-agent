import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

export interface Slot {
  start: string; // ISO
  end: string;
}

export interface DraftedEmail {
  subject: string;
  body: string;
}

export interface NotifyPayload {
  channel: "smtp" | "gmail";
  subject: string;
  body: string;
  slots: Slot[];
}

export function useDraftEmail(applicationId: number) {
  return useMutation({
    mutationFn: (slots: Slot[]) =>
      api<DraftedEmail>(`/api/applications/${applicationId}/draft-email`, {
        method: "POST",
        json: { slots },
      }),
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "Draft failed");
    },
  });
}

export function useSendNotification(applicationId: number, jobId?: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: NotifyPayload) =>
      api<{ notification_id: number; external_id: string }>(
        `/api/applications/${applicationId}/notify`,
        { method: "POST", json: payload },
      ),
    onSuccess: () => {
      toast.success("Invitation sent");
      queryClient.invalidateQueries({
        queryKey: queryKeys.application(applicationId),
      });
      if (jobId !== undefined) {
        queryClient.invalidateQueries({
          queryKey: queryKeys.jobApplications(jobId),
        });
      }
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "Send failed");
    },
  });
}
