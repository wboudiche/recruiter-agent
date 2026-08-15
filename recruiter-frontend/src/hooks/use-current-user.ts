import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
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
    retry: false,
  });
}

/** False for viewers. Cosmetic only — the server's 403s are the real
 *  gate; this exists so a viewer is not shown buttons that cannot work. */
export function useCanWrite(): boolean {
  const me = useCurrentUser();
  return me.data ? me.data.role !== "viewer" : false;
}
