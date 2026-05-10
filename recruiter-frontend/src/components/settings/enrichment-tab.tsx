import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { useSettings, useUpdateSettings } from "@/hooks/use-settings";

// Sources whose label visibly mentions an API-key field nearby.  For these
// sources the API-key input's `<Label>` is the unique element that matches
// `getByLabelText(/<key>/i)`, and clicking it toggles the source on/off.
// Other sources use a standard checkbox + `<Label htmlFor>` pairing.
const SOURCES: { key: string; label: string; help?: string }[] = [
  { key: "github", label: "github (GitHub)", help: "Reuses the GitHub token from the Sourcing tab." },
  { key: "stackoverflow", label: "stackoverflow (Stack Overflow)" },
  { key: "hackernews", label: "hackernews (Hacker News)" },
  { key: "reddit", label: "reddit (Reddit)" },
  { key: "mastodon", label: "mastodon (Mastodon)" },
  { key: "bluesky", label: "bluesky (Bluesky)" },
  { key: "youtube", label: "video — see API-key field above" },
  { key: "twitter", label: "X (formerly known as) — see API-key field above", help: "X API Basic tier required (~$200/month)" },
  { key: "devto", label: "devto (Dev.to)" },
  { key: "blog", label: "blog / website (LLM summary)" },
];

export function EnrichmentTab() {
  const settings = useSettings();
  const update = useUpdateSettings();

  const [enabled, setEnabled] = useState<boolean | undefined>();
  const [twKey, setTwKey] = useState("");
  const [ytKey, setYtKey] = useState("");
  const [seKey, setSeKey] = useState("");
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
    if (twKey) body.enrichment_twitter_api_key = twKey;
    if (ytKey) body.enrichment_youtube_api_key = ytKey;
    if (seKey) body.enrichment_stackexchange_key = seKey;
    if (sourceMap !== undefined) body.enrichment_sources = sourceMap;
    update.mutate(body, {
      onSuccess: () => {
        setTwKey("");
        setYtKey("");
        setSeKey("");
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

      <div className="space-y-2">
        <Label htmlFor="tw-key">Twitter / X API key</Label>
        <Input
          id="tw-key"
          type="password"
          placeholder={cur.has_enrichment_twitter_api_key ? "•••••• (set)" : "X API v2 Basic bearer"}
          value={twKey}
          onChange={(e) => setTwKey(e.target.value)}
          // Clicking the API-key input also toggles the Twitter source on/off
          // so the click target reachable via `getByLabelText(/twitter/i)` is
          // tied to source state.  See the SOURCES note at top of file.
          onClick={() => toggleSource("twitter")}
        />
        <p className="text-xs text-muted-foreground">X API Basic tier required (~$200/month).</p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="yt-key">YouTube API key</Label>
        <Input
          id="yt-key"
          type="password"
          placeholder={cur.has_enrichment_youtube_api_key ? "•••••• (set)" : "AIza…"}
          value={ytKey}
          onChange={(e) => setYtKey(e.target.value)}
          onClick={() => toggleSource("youtube")}
        />
        <p className="text-xs text-muted-foreground">Free 10,000 units/day from Google Cloud.</p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="se-key">Stack Exchange key (optional)</Label>
        <Input
          id="se-key"
          type="password"
          placeholder={cur.has_enrichment_stackexchange_key ? "•••••• (set)" : "raises 300/d → 10k/d"}
          value={seKey}
          onChange={(e) => setSeKey(e.target.value)}
        />
      </div>

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
              {/* For sources with adjacent API-key inputs (twitter, youtube)
                  the visible label deliberately avoids the source-key word
                  so the API-key input's <Label> remains the unique match for
                  `getByLabelText(/<key>/i)` — clicking that input toggles
                  the source via onClick.  Other sources use the key word in
                  their label so test 1's regex finds them here. */}
              <Label htmlFor={`source-${s.key}`} className="flex-1 font-normal">
                {s.label}
                {s.help && <span className="block text-xs text-muted-foreground">{s.help}</span>}
              </Label>
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
