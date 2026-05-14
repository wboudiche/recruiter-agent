import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

export interface ExperienceItem {
  title: string | null;
  company: string | null;
  start: string | null;
  end: string | null;
  description: string | null;
}

export interface EducationItem {
  school: string | null;
  degree: string | null;
  field: string | null;
  start: string | null;
  end: string | null;
}

export interface LinkItem {
  label: string;
  url: string;
}

export interface CandidateRead {
  id: number;
  full_name: string | null;
  email: string | null;
  phone: string | null;
  location: string | null;
  headline: string | null;
  summary: string | null;
  skills: string[];
  experience: ExperienceItem[];
  education: EducationItem[];
  links: LinkItem[];
  source_type: string | null;
  source_url: string | null;
  resume_path: string | null;
  photo_url: string | null;
  created_at: string;
  updated_at: string;
}

export function useCandidate(candidateId: number | undefined) {
  return useQuery({
    queryKey: candidateId !== undefined ? queryKeys.candidate(candidateId) : ["candidates", "none"],
    queryFn: () => api<CandidateRead>(`/api/candidates/${candidateId}`),
    enabled: candidateId !== undefined && !Number.isNaN(candidateId),
  });
}

export function useUpdateCandidate(candidateId: number | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: { photo_url?: string | null }) =>
      api<CandidateRead>(`/api/candidates/${candidateId}`, {
        method: "PATCH",
        json: patch,
      }),
    onSuccess: (data) => {
      if (candidateId !== undefined) {
        qc.setQueryData(queryKeys.candidate(candidateId), data);
      }
      toast.success("Candidate updated");
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Update failed"),
  });
}
