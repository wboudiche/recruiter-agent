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
    | "scored"
    | "validated"
    | "invited"
    | "scheduled"
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
  rejected_at: string | null;
  created_at: string;
  updated_at: string;
}

export function useJobApplications(jobId: number) {
  return useQuery({
    queryKey: queryKeys.jobApplications(jobId),
    queryFn: () => api<ApplicationRead[]>(`/api/jobs/${jobId}/applications`),
    enabled: !Number.isNaN(jobId),
  });
}
