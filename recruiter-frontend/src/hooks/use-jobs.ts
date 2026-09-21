import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

export interface CriteriaItem {
  name: string;
  weight: number;
  description: string;
}

export interface JobRead {
  id: number;
  title: string;
  description: string;
  criteria: CriteriaItem[];
  status: string;
  default_interview_template_id?: number | null;
  created_at: string;
  updated_at: string;
}

export function useJobs() {
  return useQuery({
    queryKey: queryKeys.jobs(),
    queryFn: () => api<JobRead[]>("/api/jobs"),
  });
}
