import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

export interface SettingsRead {
  default_llm_provider: string;
  has_anthropic_api_key: boolean;
  local_llm_url: string | null;
  model_overrides: Record<string, unknown>;
  has_google_oauth_tokens: boolean;
  has_smtp_config: boolean;
  recruiter_name: string | null;
  recruiter_email: string | null;
  monthly_llm_spend_cap_usd: number | null;
}

export interface SmtpConfigInput {
  host: string;
  port: number;
  user: string;
  password: string;
  from_email: string;
}

export interface SettingsUpdate {
  default_llm_provider?: string;
  anthropic_api_key?: string;
  local_llm_url?: string;
  model_overrides?: Record<string, unknown>;
  smtp_config?: SmtpConfigInput;
  recruiter_name?: string;
  recruiter_email?: string;
  monthly_llm_spend_cap_usd?: number;
}

export function useSettings() {
  return useQuery({
    queryKey: queryKeys.settings(),
    queryFn: () => api<SettingsRead>("/api/settings"),
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: SettingsUpdate) =>
      api<SettingsRead>("/api/settings", { method: "PUT", json: payload }),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.settings(), data);
      toast.success("Settings saved");
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "Save failed");
    },
  });
}
