import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

export interface SettingsRead {
  default_llm_provider: string;
  has_anthropic_api_key: boolean;
  local_llm_url: string | null;
  has_local_llm_api_key: boolean;
  model_overrides: Record<string, unknown>;
  has_google_oauth_tokens: boolean;
  has_smtp_config: boolean;
  recruiter_name: string | null;
  recruiter_email: string | null;
  monthly_llm_spend_cap_usd: number | null;
  search_provider: string | null;
  search_engine_id: string | null;
  has_search_api_key: boolean;
  has_github_token: boolean;
  enrichment_enabled: boolean;
  has_enrichment_twitter_api_key: boolean;
  has_enrichment_youtube_api_key: boolean;
  has_enrichment_stackexchange_key: boolean;
  enrichment_sources: Record<string, boolean>;
}

export interface SmtpConfigInput {
  host: string;
  port: number;
  user: string;
  password: string;
  from_email: string;
  use_starttls?: boolean;
}

export interface SettingsUpdate {
  default_llm_provider?: string;
  anthropic_api_key?: string;
  local_llm_url?: string;
  local_llm_api_key?: string;
  model_overrides?: Record<string, unknown>;
  smtp_config?: SmtpConfigInput;
  recruiter_name?: string;
  recruiter_email?: string;
  monthly_llm_spend_cap_usd?: number;
  search_provider?: string;
  search_api_key?: string;
  search_engine_id?: string;
  github_token?: string;
  enrichment_enabled?: boolean;
  enrichment_twitter_api_key?: string;
  enrichment_youtube_api_key?: string;
  enrichment_stackexchange_key?: string;
  enrichment_sources?: Record<string, boolean>;
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
