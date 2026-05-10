import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError } from "@/lib/api";
import { useSettings, useUpdateSettings } from "@/hooks/use-settings";

type Provider = "google_cse" | "brave" | "searxng" | "serpapi";

const PROVIDER_LABELS: Record<Provider, string> = {
  google_cse: "Google Custom Search",
  brave: "Brave Search",
  searxng: "SearXNG (self-hosted)",
  serpapi: "SerpAPI (Google)",
};

export function SourcingTab() {
  const settings = useSettings();
  const update = useUpdateSettings();
  const [provider, setProvider] = useState<Provider | undefined>();
  const [apiKey, setApiKey] = useState("");
  const [cseOrUrl, setCseOrUrl] = useState<string | undefined>();
  const [ghToken, setGhToken] = useState("");

  // Reset typed inputs whenever the active provider changes so a stale
  // value typed under a previous provider can't leak into the next save.
  useEffect(() => {
    setApiKey("");
    setCseOrUrl(undefined);
  }, [provider]);

  if (settings.isLoading) return <p>Loading…</p>;
  if (!settings.data) return <p>No settings.</p>;

  const cur = settings.data;
  const effProvider = (provider ?? cur.search_provider ?? "google_cse") as Provider;
  // Persisted search_engine_id is meaningful only for the provider it was
  // saved under. When viewing a different provider, start the field empty.
  const persistedRelevant = effProvider === cur.search_provider;
  const effCseOrUrl = cseOrUrl ?? (persistedRelevant ? (cur.search_engine_id ?? "") : "");

  const showApiKey =
    effProvider === "google_cse" || effProvider === "brave" || effProvider === "serpapi";
  const showCseId = effProvider === "google_cse";
  const showInstanceUrl = effProvider === "searxng";

  function save() {
    const body: Record<string, unknown> = {};
    if (provider !== undefined && provider !== cur.search_provider) {
      body.search_provider = provider;
    } else if (cur.search_provider === null) {
      body.search_provider = effProvider;
    }
    if (showApiKey && apiKey) body.search_api_key = apiKey;
    if ((showCseId || showInstanceUrl) && cseOrUrl !== undefined && cseOrUrl !== (cur.search_engine_id ?? "")) {
      body.search_engine_id = cseOrUrl;
    }
    if (ghToken) body.github_token = ghToken;
    update.mutate(body, {
      onSuccess: () => {
        setApiKey("");
        setGhToken("");
        toast.success("Sourcing settings saved");
      },
      onError: (err) => {
        toast.error(err instanceof ApiError ? err.detail : "Save failed");
      },
    });
  }

  return (
    <div className="space-y-4 max-w-md">
      <div className="space-y-2">
        <Label htmlFor="sourcing-provider">Provider (LinkedIn + Web search)</Label>
        <Select value={effProvider} onValueChange={(v) => setProvider(v as Provider)}>
          <SelectTrigger id="sourcing-provider" aria-label="Provider">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="google_cse">{PROVIDER_LABELS.google_cse}</SelectItem>
            <SelectItem value="brave">{PROVIDER_LABELS.brave}</SelectItem>
            <SelectItem value="serpapi">{PROVIDER_LABELS.serpapi}</SelectItem>
            <SelectItem value="searxng">{PROVIDER_LABELS.searxng}</SelectItem>
          </SelectContent>
        </Select>
        {effProvider === "google_cse" && (
          <p className="text-xs text-muted-foreground">
            Configure a Custom Search Engine at{" "}
            <a className="underline" href="https://cse.google.com" target="_blank" rel="noreferrer">
              cse.google.com
            </a>{" "}
            and enable the Custom Search API in Google Cloud Console.
          </p>
        )}
        {effProvider === "brave" && (
          <p className="text-xs text-muted-foreground">
            Free key (no card, 2000 queries/month) at{" "}
            <a className="underline" href="https://brave.com/search/api/" target="_blank" rel="noreferrer">
              brave.com/search/api
            </a>.
          </p>
        )}
        {effProvider === "serpapi" && (
          <p className="text-xs text-muted-foreground">
            Returns Google SERPs without a Google billing account. Free 100 searches/month at{" "}
            <a className="underline" href="https://serpapi.com" target="_blank" rel="noreferrer">
              serpapi.com
            </a>.
          </p>
        )}
        {effProvider === "searxng" && (
          <p className="text-xs text-muted-foreground">
            Run SearXNG via Docker. In <code>settings.yml</code> ensure{" "}
            <code>search.formats</code> includes <code>json</code>.
          </p>
        )}
      </div>

      {showApiKey && (
        <div className="space-y-2">
          <Label htmlFor="sourcing-api-key">API key</Label>
          <Input
            id="sourcing-api-key"
            type="password"
            placeholder={
              cur.has_search_api_key
                ? "•••••• (set)"
                : effProvider === "brave"
                  ? "brv_…"
                  : effProvider === "serpapi"
                    ? "serpapi key"
                    : "AIza…"
            }
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>
      )}

      {showCseId && (
        <div className="space-y-2">
          <Label htmlFor="sourcing-cse-id">CSE ID (cx)</Label>
          <Input
            id="sourcing-cse-id"
            placeholder="abcd1234:efgh5678"
            value={effCseOrUrl}
            onChange={(e) => setCseOrUrl(e.target.value)}
          />
        </div>
      )}

      {showInstanceUrl && (
        <div className="space-y-2">
          <Label htmlFor="sourcing-instance-url">Instance URL</Label>
          <Input
            id="sourcing-instance-url"
            placeholder="http://localhost:8080"
            value={effCseOrUrl}
            onChange={(e) => setCseOrUrl(e.target.value)}
          />
        </div>
      )}

      <div className="space-y-2">
        <Label htmlFor="sourcing-gh-token">GitHub personal access token (optional)</Label>
        <Input
          id="sourcing-gh-token"
          type="password"
          placeholder={
            cur.has_github_token ? "•••••• (set)" : "ghp_… (raises rate limit)"
          }
          value={ghToken}
          onChange={(e) => setGhToken(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          GitHub search works without a token but is limited to 60 requests/hour.
        </p>
      </div>

      <Button onClick={save} disabled={update.isPending}>
        {update.isPending ? "Saving…" : "Save"}
      </Button>
    </div>
  );
}
