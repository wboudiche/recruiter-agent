import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

export interface UserRead {
  id: number;
  email: string;
  name: string | null;
  picture: string | null;
  role: "admin" | "recruiter" | "viewer";
}

export function useCurrentUser() {
  return useQuery({
    queryKey: queryKeys.currentUser(),
    queryFn: () => api<UserRead>("/api/auth/me"),
    // A single transient failure here now hides every write control on
    // the board (useCanWrite defaults to false), which nothing depended
    // on before this query grew that consumer. Retry a couple of times so
    // a network blip self-heals instead of stranding a recruiter until
    // they reload. Never retry a 401 — that's an auth decision (api()
    // already redirects to /login for it), not a blip.
    retry: (failureCount, error) =>
      failureCount < 2 && !(error instanceof ApiError && error.status === 401),
  });
}

/** False for viewers. Cosmetic only — the server's 403s are the real
 *  gate; this exists so a viewer is not shown buttons that cannot work. */
export function useCanWrite(): boolean {
  const me = useCurrentUser();
  return me.data ? me.data.role !== "viewer" : false;
}

/** True only once the role has actually resolved to viewer — false while
 *  loading, so a real admin/recruiter never sees a "read-only" notice
 *  flash before their role has loaded. `useCanWrite()` alone can't make
 *  this distinction: both "still loading" and "is a viewer" read false. */
export function useIsKnownViewer(): boolean {
  const me = useCurrentUser();
  const canWrite = useCanWrite();
  return !me.isLoading && !canWrite;
}
