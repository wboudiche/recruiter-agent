import { useState } from "react";
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

export function SourcingTab() {
  const settings = useSettings();
  const update = useUpdateSettings();
  const [provider, setProvider] = useState<string | undefined>();
  const [apiKey, setApiKey] = useState("");
  const [cseId, setCseId] = useState<string | undefined>();
  const [ghToken, setGhToken] = useState("");

  if (settings.isLoading) return <p>Loading…</p>;
  if (!settings.data) return <p>No settings.</p>;

  const cur = settings.data;
  const effProvider = provider ?? cur.search_provider ?? "google_cse";
  const effCse = cseId ?? cur.search_engine_id ?? "";

  function save() {
    const body: Record<string, unknown> = {};
    if (provider !== undefined && provider !== cur.search_provider)
      body.search_provider = provider;
    if (apiKey) body.search_api_key = apiKey;
    if (cseId !== undefined && cseId !== (cur.search_engine_id ?? ""))
      body.search_engine_id = cseId;
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
        <Label>Provider (LinkedIn + Web search)</Label>
        <Select value={effProvider} onValueChange={setProvider}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="google_cse">Google Custom Search</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">
          Configure a Custom Search Engine at{" "}
          <a className="underline" href="https://cse.google.com" target="_blank" rel="noreferrer">cse.google.com</a>{" "}
          and enable the Custom Search API in Google Cloud Console.
        </p>
      </div>

      <div className="space-y-2">
        <Label>API key</Label>
        <Input
          type="password"
          placeholder={cur.has_search_api_key ? "•••••• (set)" : "AIza…"}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
      </div>

      <div className="space-y-2">
        <Label>CSE ID (cx)</Label>
        <Input
          placeholder="abcd1234:efgh5678"
          value={effCse}
          onChange={(e) => setCseId(e.target.value)}
        />
      </div>

      <div className="space-y-2">
        <Label>GitHub personal access token (optional)</Label>
        <Input
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
