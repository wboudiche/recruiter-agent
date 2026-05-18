import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import type { CandidateRead } from "@/hooks/use-candidate";

/**
 * Fan-out candidate lookups for a set of IDs. Shares cache keys with
 * `useCandidate`, so opening the application detail afterwards is
 * instant. Returns a Map keyed by candidate id; missing entries simply
 * stay absent (consumers should fall back to a placeholder).
 */
export function useCandidatesByIds(ids: number[]): Map<number, CandidateRead> {
  const unique = useMemo(() => Array.from(new Set(ids)), [ids]);
  const results = useQueries({
    queries: unique.map((id) => ({
      queryKey: queryKeys.candidate(id),
      queryFn: () => api<CandidateRead>(`/api/candidates/${id}`),
      enabled: !Number.isNaN(id),
      staleTime: 5 * 60_000,
    })),
  });
  const map = new Map<number, CandidateRead>();
  results.forEach((r, i) => {
    if (r.data) map.set(unique[i], r.data);
  });
  return map;
}
