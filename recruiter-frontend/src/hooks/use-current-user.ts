import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

export interface UserRead {
  id: number;
  email: string;
  name: string | null;
  picture: string | null;
}

export function useCurrentUser() {
  return useQuery({
    queryKey: queryKeys.currentUser(),
    queryFn: () => api<UserRead>("/api/auth/me"),
    retry: false,
  });
}
