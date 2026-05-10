import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useReEnrich } from "@/hooks/use-application-mutations";

interface Signal {
  type: string;
  summary: string;
  url?: string | null;
  timestamp?: string | null;
}

interface Result {
  source: string;
  profile_url: string;
  confidence: number;
  discovered: boolean;
  signals: Signal[];
  summary: string;
}

export interface Bundle {
  fetched_at: string;
  expires_at: string;
  discovery_consent: boolean;
  results: Result[];
  errors: { source: string; error: string; transient: boolean }[];
}

export function EnrichmentSection({
  applicationId,
  enrichment,
}: {
  applicationId: number;
  enrichment: Bundle | null;
}) {
  const reEnrich = useReEnrich();
  const [showLow, setShowLow] = useState(false);
  if (!enrichment) return null;

  const high = enrichment.results.filter((r) => r.confidence >= 0.75);
  const low = enrichment.results.filter((r) => r.confidence < 0.75);

  return (
    <section className="space-y-4 rounded border p-4">
      <header className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Enrichment</h3>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">
            cached {new Date(enrichment.fetched_at).toLocaleDateString()},
            expires {new Date(enrichment.expires_at).toLocaleDateString()}
          </span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => reEnrich.mutate(applicationId)}
            disabled={reEnrich.isPending}
          >
            {reEnrich.isPending ? "Queuing…" : "Re-enrich now"}
          </Button>
        </div>
      </header>

      {high.length === 0 && low.length === 0 && (
        <p className="text-sm text-muted-foreground">No public profiles found.</p>
      )}

      {high.map((r) => (
        <ResultCard key={r.source} result={r} />
      ))}

      {low.length > 0 && (
        <div>
          <button
            type="button"
            className="text-sm underline"
            onClick={() => setShowLow((v) => !v)}
            aria-expanded={showLow}
          >
            {showLow ? "Hide" : "Show"} {low.length} unconfirmed match
            {low.length > 1 ? "es" : ""}
          </button>
          <div
            className="mt-2 space-y-2"
            hidden={!showLow}
            style={showLow ? undefined : { display: "none" }}
          >
            {low.map((r) => (
              <ResultCard key={r.source} result={r} />
            ))}
          </div>
        </div>
      )}

      {enrichment.errors.length > 0 && (
        <div className="border-t pt-2">
          <p className="text-xs font-medium text-muted-foreground mb-1">
            Some sources failed:
          </p>
          <ul className="space-y-1 text-xs">
            {enrichment.errors.map((e, i) => (
              <li key={i} className="text-destructive">
                <span className="font-mono">{e.source}</span>: {e.error}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function ResultCard({ result }: { result: Result }) {
  return (
    <article className="space-y-2 rounded border p-3">
      <div className="flex items-center gap-2">
        <span className="font-medium">{result.source}</span>
        <Badge variant={result.confidence >= 0.75 ? "default" : "secondary"}>
          conf {result.confidence.toFixed(2)}
        </Badge>
        {result.discovered && <Badge variant="outline">Discovered</Badge>}
        <a
          href={result.profile_url}
          target="_blank"
          rel="noreferrer"
          className="ml-auto text-xs underline"
        >
          profile ↗
        </a>
      </div>
      <p className="text-sm">{result.summary}</p>
      <ul className="space-y-1">
        {result.signals.map((s, i) => (
          <li key={i} className="text-xs flex gap-2">
            <span className="text-muted-foreground uppercase">{s.type}</span>
            <span>{s.summary}</span>
            {s.url && (
              <a
                href={s.url}
                target="_blank"
                rel="noreferrer"
                className="underline"
              >
                ↗
              </a>
            )}
          </li>
        ))}
      </ul>
    </article>
  );
}
