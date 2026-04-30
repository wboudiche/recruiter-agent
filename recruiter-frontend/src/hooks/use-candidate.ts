import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export interface CandidateRead {
  id: number;
  full_name: string | null;
  email: string | null;
  phone: string | null;
  location: string | null;
  headline: string | null;
  summary: string | null;
  skills: string[];
  experience: { title: string | null; company: string | null }[];
  education: { school: string | null }[];
  links: { label: string; url: string }[];
  source_type: string | null;
  source_url: string | null;
  resume_path: string | null;
  created_at: string;
  updated_at: string;
}

export function useCandidate(candidateId: number | undefined) {
  return useQuery({
    queryKey: ["candidate", candidateId],
    queryFn: () => api<CandidateRead>(`/api/candidates/${candidateId}`),
    enabled: candidateId !== undefined && !Number.isNaN(candidateId),
  });
}
