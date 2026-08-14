import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

export interface UserAdminRead {
  id: number;
  email: string;
  name: string | null;
  role: "admin" | "recruiter" | "viewer";
  is_active: boolean;
  last_login_at: string | null;
}

export function useUsers() {
  return useQuery({
    queryKey: queryKeys.users(),
    queryFn: () => api<UserAdminRead[]>("/api/users"),
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      email: string; name?: string; role: string; password: string;
    }) => api<UserAdminRead>("/api/users", { method: "POST", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.users() }),
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number; role?: string; is_active?: boolean }) =>
      api<UserAdminRead>(`/api/users/${id}`, { method: "PATCH", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.users() }),
  });
}

export function useResetPassword() {
  return useMutation({
    mutationFn: ({ id, password }: { id: number; password: string }) =>
      api(`/api/users/${id}/password`, { method: "POST", json: { password } }),
  });
}
