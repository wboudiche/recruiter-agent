import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import type { JobRead } from "./use-jobs";

export function useJob(jobId: number) {
  return useQuery({
    queryKey: queryKeys.job(jobId),
    queryFn: () => api<JobRead>(`/api/jobs/${jobId}`),
    enabled: !Number.isNaN(jobId),
  });
}

export type { JobRead };
