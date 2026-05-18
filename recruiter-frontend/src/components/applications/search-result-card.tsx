import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { classifyResultUrl } from "@/lib/url-classification";

export interface SearchResult {
  name: string;
  url: string;
  snippet: string;
  source: "linkedin" | "github" | "web";
}

interface Props {
  result: SearchResult;
  jobId: number;
}

const SOURCE_LABEL: Record<SearchResult["source"], string> = {
  linkedin: "LinkedIn",
  github: "GitHub",
  web: "Web",
};

export function SearchResultCard({ result, jobId }: Props) {
  const qc = useQueryClient();
  const [added, setAdded] = useState(false);
  // Block aggregator / job-board URLs at the UI level: adding them creates
  // a candidate row the extractor can't populate (the page isn't a single
  // person), and some of those sites (bayt, upwork, indeed, ...) also
  // return 403 to scrapers anyway.
  const classification = classifyResultUrl(result.url);
  const add = useMutation({
    mutationFn: () =>
      api(`/api/jobs/${jobId}/candidates`, {
        method: "POST",
        // Forward the search-result hints so the backend can pre-fill
        // `candidate.full_name` / `headline`. Critical for LinkedIn URLs,
        // which can't be auto-scraped: without these, the card stays
        // labelled "Candidate #N" until the user pastes the profile.
        json: {
          kind: "url",
          url: result.url,
          name: result.name,
          snippet: result.snippet,
        },
      }),
    onSuccess: () => {
      toast.success("Added to pipeline");
      qc.invalidateQueries({ queryKey: queryKeys.jobApplications(jobId) });
      setAdded(true);
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "Add failed");
    },
  });

  return (
    <div className="border rounded p-2 space-y-1 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-sm truncate">{result.name}</span>
        <span className="text-muted-foreground uppercase text-[10px] shrink-0">
          {SOURCE_LABEL[result.source]}
        </span>
      </div>
      <p className="text-muted-foreground line-clamp-2">{result.snippet}</p>
      <div className="flex items-center justify-between gap-2">
        <a
          href={result.url}
          target="_blank"
          rel="noreferrer"
          className="underline truncate min-w-0"
        >
          {result.url}
        </a>
        {classification.kind === "profile" ? (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => add.mutate()}
            disabled={add.isPending || added}
          >
            {added ? "Added ✓" : add.isPending ? "Adding…" : "Add"}
          </Button>
        ) : (
          <span
            className="shrink-0 border border-[hsl(var(--ed-amber)/0.4)] px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-[hsl(var(--ed-amber))]"
            title={classification.reason}
          >
            {classification.reason}
          </span>
        )}
      </div>
    </div>
  );
}
