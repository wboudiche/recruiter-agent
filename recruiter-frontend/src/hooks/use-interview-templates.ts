import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import type { EditableQuestion } from "@/components/interview/question-list-editor";

export type ProbeMode = "score_gaps" | "profile" | "none";

export interface InterviewTemplate {
  id: number;
  name: string;
  description: string | null;
  questions: EditableQuestion[];
  probe_mode: ProbeMode;
  include_job_questions: boolean;
  is_active: boolean;
}

export function useInterviewTemplates(includeArchived = false, enabled = true) {
  return useQuery({
    queryKey: queryKeys.interviewTemplates(includeArchived),
    queryFn: () =>
      api<InterviewTemplate[]>(`/api/interview-templates?include_archived=${includeArchived}`),
    enabled,
  });
}

/** Create when `id` is undefined, otherwise PATCH. Archiving is a PATCH of
 *  `{ is_active: false }`. Invalidates both archived and active lists. */
export function useSaveInterviewTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id?: number; body: Partial<InterviewTemplate> }) =>
      id === undefined
        ? api<InterviewTemplate>("/api/interview-templates", { method: "POST", json: body })
        : api<InterviewTemplate>(`/api/interview-templates/${id}`, { method: "PATCH", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["interview-templates"] }),
  });
}
