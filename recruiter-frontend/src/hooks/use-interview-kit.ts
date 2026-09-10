import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

export type Rating = "strong" | "adequate" | "weak";

export interface KitQuestion {
  id: string;
  text: string;
  source: "baseline" | "probe";
  criterion?: string | null;
  answer: string | null;
  rating: Rating | null;
}

export interface InterviewKit {
  status: "generating" | "ready" | "error";
  error?: string | null;
  generated_at?: string | null;
  submitted_at?: string | null;
  questions: KitQuestion[];
}

export function useInterviewKit(applicationId: number) {
  const qc = useQueryClient();
  const key = queryKeys.interviewKit(applicationId);
  const path = `/api/applications/${applicationId}/interview-kit`;

  const query = useQuery({
    queryKey: key,
    queryFn: () => api<{ kit: InterviewKit | null }>(path),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: key });

  const generate = useMutation({
    mutationFn: () => api(`${path}/generate`, { method: "POST" }),
    onSuccess: invalidate,
  });

  const patch = useMutation({
    mutationFn: (questions: KitQuestion[]) =>
      api(path, { method: "PATCH", json: { questions } }),
    onSuccess: invalidate,
  });

  const submit = useMutation({
    mutationFn: () => api(`${path}/submit`, { method: "POST" }),
    onSuccess: () => {
      invalidate();
      // The stage changed, so the kanban and the detail header are stale too.
      qc.invalidateQueries({ queryKey: queryKeys.application(applicationId) });
    },
  });

  return {
    kit: query.data?.kit ?? null,
    isLoading: query.isLoading,
    generate,
    patch,
    submit,
  };
}
