import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  SecretField,
  secretToPayload,
  UNCHANGED,
  type SecretValue,
} from "./secret-field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError } from "@/lib/api";
import { useSettings, useUpdateSettings } from "@/hooks/use-settings";
import { LinkedInConnect } from "@/components/settings/linkedin-connect";

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
  const [apiKey, setApiKey] = useState<SecretValue>(UNCHANGED);
  const [cseOrUrl, setCseOrUrl] = useState<string | undefined>();
  const [ghToken, setGhToken] = useState<SecretValue>(UNCHANGED);
  const [apifyKey, setApifyKey] = useState<SecretValue>(UNCHANGED);
  const [apifyActorId, setApifyActorId] = useState<string | undefined>();

  // Reset typed inputs whenever the active provider changes so a stale
  // value typed under a previous provider can't leak into the next save.
  useEffect(() => {
    setApiKey(UNCHANGED);
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
    if (showApiKey) {
      const v = secretToPayload(apiKey);
      if (v !== undefined) body.search_api_key = v;
    }
    if ((showCseId || showInstanceUrl) && cseOrUrl !== undefined && cseOrUrl !== (cur.search_engine_id ?? "")) {
      body.search_engine_id = cseOrUrl;
    }
    const ghPayload = secretToPayload(ghToken);
    if (ghPayload !== undefined) body.github_token = ghPayload;
    const apifyPayload = secretToPayload(apifyKey);
    if (apifyPayload !== undefined) body.apify_api_key = apifyPayload;
    if (apifyActorId !== undefined && apifyActorId !== (cur.apify_actor_id ?? "")) {
      body.apify_actor_id = apifyActorId;
    }
    update.mutate(body, {
      onSuccess: () => {
        setApiKey(UNCHANGED);
        setGhToken(UNCHANGED);
        setApifyKey(UNCHANGED);
        setApifyActorId(undefined);
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
        <SecretField
          id="sourcing-api-key"
          label="API key"
          isSet={cur.has_search_api_key}
          value={apiKey}
          onChange={setApiKey}
          unsetPlaceholder={
            effProvider === "brave"
              ? "brv_…"
              : effProvider === "serpapi"
                ? "serpapi key"
                : "AIza…"
          }
        />
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

      <SecretField
        id="sourcing-gh-token"
        label="GitHub personal access token (optional)"
        isSet={cur.has_github_token}
        value={ghToken}
        onChange={setGhToken}
        unsetPlaceholder="ghp_… (raises rate limit)"
        help="GitHub search works without a token but is limited to 60 requests/hour."
      />

      <SecretField
        id="sourcing-apify"
        label="Apify API token (optional, commercial LinkedIn extraction)"
        isSet={cur.has_apify_api_key}
        value={apifyKey}
        onChange={setApifyKey}
        unsetPlaceholder="apify_api_… (from apify.com)"
        help={
          <span className="leading-snug">
            When set, LinkedIn URL adds route through Apify first
            (~$0.01/profile, reliable, no anti-bot fight) with the Playwright
            path as fallback. Without it, Playwright is used directly. Sign
            up at{" "}
            <a
              href="https://apify.com"
              target="_blank"
              rel="noreferrer"
              className="underline"
            >
              apify.com
            </a>
            .
          </span>
        }
      />

      <div className="space-y-2">
        <Label htmlFor="sourcing-apify-actor">
          Apify actor (LinkedIn profile scraper)
        </Label>
        <Input
          id="sourcing-apify-actor"
          type="text"
          placeholder="dev_fusion/linkedin-profile-scraper (default)"
          value={apifyActorId ?? (cur.apify_actor_id ?? "")}
          onChange={(e) => setApifyActorId(e.target.value)}
        />
        <p className="text-xs text-muted-foreground leading-snug">
          Actor slug in <code>username/actor-name</code> form. Leave
          empty to use the default. Some actors restrict API access by
          Apify plan tier — if calls fail with{" "}
          <em>"free plan…"</em>, swap to one that allows free-plan API
          calls (e.g. <code>apify/linkedin-profile-scraper</code>,{" "}
          <code>curious_coder/linkedin-profile-scraper</code>).
        </p>
      </div>

      <Button onClick={save} disabled={update.isPending}>
        {update.isPending ? "Saving…" : "Save"}
      </Button>

      <LinkedInConnect />
    </div>
  );
}
