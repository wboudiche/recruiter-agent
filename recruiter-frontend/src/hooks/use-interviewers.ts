import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

export interface InterviewerRead {
  user_id: number;
  name: string | null;
  email: string;
  submitted_at: string | null;
  /** Which track of the live round (phase 3); absent from older servers. */
  track?: string;
}

export interface DirectoryUser {
  id: number;
  name: string | null;
  email: string;
  role: "admin" | "recruiter" | "viewer";
}

export function useInterviewers(applicationId: number) {
  const qc = useQueryClient();
  const key = queryKeys.interviewers(applicationId);
  const path = `/api/applications/${applicationId}/interviewers`;
  const query = useQuery({
    queryKey: key,
    queryFn: () => api<InterviewerRead[]>(path),
    enabled: !Number.isNaN(applicationId),
  });
  const setInterviewers = useMutation({
    // A bare list is the whole panel of a one-track round; `{ userIds,
    // track }` sets one track's panel (`?track=`).
    mutationFn: (arg: number[] | { userIds: number[]; track: string }) => {
      const { userIds, track } = Array.isArray(arg) ? { userIds: arg, track: null } : arg;
      const url = track === null ? path : `${path}?track=${encodeURIComponent(track)}`;
      return api<InterviewerRead[]>(url, { method: "PUT", json: { user_ids: userIds } });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: queryKeys.interviewKit(applicationId) });
      qc.invalidateQueries({ queryKey: queryKeys.application(applicationId) });
    },
  });
  return {
    interviewers: query.data ?? [],
    isLoading: query.isLoading,
    // Distinguish "request failed" from "loaded, zero interviewers" — the
    // picker must not let Assign open (and Save unassign everyone) off the
    // back of an empty list that's actually an error.
    isError: query.isError,
    setInterviewers,
  };
}

/** Only fetched when the picker opens — a recruiter-only endpoint, and
 *  viewers never open the picker. */
export function useUserDirectory(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.userDirectory(),
    queryFn: () => api<DirectoryUser[]>("/api/users/directory"),
    enabled,
  });
}
