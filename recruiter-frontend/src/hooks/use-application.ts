import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import type { ApplicationRead } from "./use-job-applications";

export function useApplication(applicationId: number) {
  return useQuery({
    queryKey: queryKeys.application(applicationId),
    queryFn: () => api<ApplicationRead>(`/api/applications/${applicationId}`),
    enabled: !Number.isNaN(applicationId),
  });
}
