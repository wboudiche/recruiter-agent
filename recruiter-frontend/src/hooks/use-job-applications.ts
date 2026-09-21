import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

export interface ApplicationRead {
  id: number;
  job_id: number;
  candidate_id: number;
  stage:
    | "sourced"
    | "extracting"
    | "enriching"
    | "scored"
    | "validated"
    | "invited"
    | "scheduled"
    | "interviewed"
    | "offer"
    | "hired"
    | "rejected";
  score: number | null;
  score_breakdown:
    | { criterion: string; weight: number; score: number; rationale: string }[]
    | null;
  score_rationale: string | null;
  notes: string | null;
  validated_at: string | null;
  invited_at: string | null;
  scheduled_at: string | null;
  /** Which interview round is in progress; 1 unless reopened. */
  interview_round?: number;
  interviewed_at?: string | null;
  offer_at?: string | null;
  hired_at?: string | null;
  rejected_at: string | null;
  rejection_reason?: string | null;
  /** Interviewer sheets assigned / submitted. Shown as "n/m sheets in" while scheduled. */
  sheets_total?: number;
  sheets_submitted?: number;
  created_at: string;
  updated_at: string;
  awaiting_paste: boolean;
  /** Why the pipeline stopped, when it did. Null when healthy. */
  last_error?: string | null;
  /** id of the event `last_error` came from. Two consecutive failures often
   * carry identical text, so the message alone cannot tell "nothing new" from
   * "it failed again the same way". */
  last_error_event_id?: number | null;
  enrichment?: unknown | null;
}

export function useJobApplications(jobId: number) {
  return useQuery({
    queryKey: queryKeys.jobApplications(jobId),
    queryFn: () => api<ApplicationRead[]>(`/api/jobs/${jobId}/applications`),
    enabled: !Number.isNaN(jobId),
  });
}
