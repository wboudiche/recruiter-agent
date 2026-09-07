import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  SecretField,
  secretToPayload,
  UNCHANGED,
  type SecretValue,
} from "./secret-field";
import { ApiError } from "@/lib/api";
import { useSettings, useUpdateSettings } from "@/hooks/use-settings";

const SOURCES: { key: string; label: string; help?: string }[] = [
  { key: "github", label: "GitHub", help: "Reuses the GitHub token from the Sourcing tab." },
  { key: "stackoverflow", label: "Stack Overflow" },
  { key: "hackernews", label: "Hacker News" },
  { key: "reddit", label: "Reddit" },
  { key: "mastodon", label: "Mastodon" },
  { key: "bluesky", label: "Bluesky" },
  { key: "youtube", label: "YouTube" },
  { key: "twitter", label: "Twitter / X", help: "X API Basic tier required (~$200/month)" },
  { key: "devto", label: "Dev.to" },
  { key: "blog", label: "Blog / website (LLM summary)" },
];

export function EnrichmentTab() {
  const settings = useSettings();
  const update = useUpdateSettings();

  const [enabled, setEnabled] = useState<boolean | undefined>();
  const [twKey, setTwKey] = useState<SecretValue>(UNCHANGED);
  const [ytKey, setYtKey] = useState<SecretValue>(UNCHANGED);
  const [seKey, setSeKey] = useState<SecretValue>(UNCHANGED);
  const [sourceMap, setSourceMap] = useState<Record<string, boolean> | undefined>();

  useEffect(() => {
    if (settings.data) {
      if (enabled === undefined) setEnabled(settings.data.enrichment_enabled);
      if (sourceMap === undefined) setSourceMap(settings.data.enrichment_sources ?? {});
    }
  }, [settings.data, enabled, sourceMap]);

  if (settings.isLoading) return <p>Loading…</p>;
  if (!settings.data) return <p>No settings.</p>;
  const cur = settings.data;
  const effEnabled = enabled ?? cur.enrichment_enabled;
  const effMap: Record<string, boolean> = sourceMap ?? cur.enrichment_sources ?? {};

  function toggleSource(name: string) {
    setSourceMap({ ...effMap, [name]: !(effMap[name] ?? true) });
  }

  function save() {
    const body: Record<string, unknown> = {};
    if (enabled !== undefined && enabled !== cur.enrichment_enabled) body.enrichment_enabled = enabled;
    const twKeyPayload = secretToPayload(twKey);
    if (twKeyPayload !== undefined) body.enrichment_twitter_api_key = twKeyPayload;
    const ytKeyPayload = secretToPayload(ytKey);
    if (ytKeyPayload !== undefined) body.enrichment_youtube_api_key = ytKeyPayload;
    const seKeyPayload = secretToPayload(seKey);
    if (seKeyPayload !== undefined) body.enrichment_stackexchange_key = seKeyPayload;
    if (sourceMap !== undefined) body.enrichment_sources = sourceMap;
    update.mutate(body, {
      onSuccess: () => {
        setTwKey(UNCHANGED);
        setYtKey(UNCHANGED);
        setSeKey(UNCHANGED);
        toast.success("Enrichment settings saved");
      },
      onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Save failed"),
    });
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="flex items-center gap-2">
        <input
          id="enrichment-enabled"
          type="checkbox"
          className="h-4 w-4"
          checked={effEnabled}
          onChange={(e) => setEnabled(e.target.checked)}
        />
        <Label htmlFor="enrichment-enabled">Enable enrichment</Label>
      </div>
      <p className="text-xs text-muted-foreground">
        Master kill switch. When off, no enrichment runs for any application.
        Per-job consent is still required for discovery and Twitter/X.
      </p>

      <SecretField
        id="tw-key"
        label="Twitter / X API key"
        isSet={cur.has_enrichment_twitter_api_key}
        value={twKey}
        onChange={setTwKey}
        unsetPlaceholder="X API v2 Basic bearer"
        help="X API Basic tier required (~$200/month)."
      />

      <SecretField
        id="yt-key"
        label="YouTube API key"
        isSet={cur.has_enrichment_youtube_api_key}
        value={ytKey}
        onChange={setYtKey}
        unsetPlaceholder="AIza…"
        help="Free 10,000 units/day from Google Cloud."
      />

      <SecretField
        id="se-key"
        label="Stack Exchange key (optional)"
        isSet={cur.has_enrichment_stackexchange_key}
        value={seKey}
        onChange={setSeKey}
        unsetPlaceholder="raises 300/d → 10k/d"
      />

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Sources</legend>
        <div className="grid grid-cols-2 gap-2">
          {SOURCES.map((s) => (
            <div key={s.key} className="flex items-start gap-2 text-sm">
              <input
                id={`source-${s.key}`}
                type="checkbox"
                className="h-4 w-4 mt-1"
                checked={effMap[s.key] ?? true}
                onChange={() => toggleSource(s.key)}
              />
              <div className="flex-1">
                <Label htmlFor={`source-${s.key}`} className="font-normal">
                  {s.label}
                </Label>
                {s.help && <p className="text-xs text-muted-foreground">{s.help}</p>}
              </div>
            </div>
          ))}
        </div>
      </fieldset>

      <Button onClick={save} disabled={update.isPending}>
        {update.isPending ? "Saving…" : "Save"}
      </Button>
    </div>
  );
}
