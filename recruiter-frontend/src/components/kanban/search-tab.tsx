import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  SearchResultCard,
  type SearchResult,
} from "@/components/applications/search-result-card";
import { api, ApiError } from "@/lib/api";

type Source = "linkedin" | "github" | "web";

interface SearchErrorItem {
  source: string;
  reason: string;
  transient: boolean;
}

interface SearchResponse {
  results: SearchResult[];
  errors: SearchErrorItem[];
}

interface Props {
  jobId: number;
}

const SOURCES: Source[] = ["linkedin", "github", "web"];
const SOURCE_LABEL: Record<Source, string> = {
  linkedin: "LinkedIn",
  github: "GitHub",
  web: "Web",
};

export function SearchTab({ jobId }: Props) {
  const [selected, setSelected] = useState<Set<Source>>(new Set());
  const [query, setQuery] = useState("");
  const [hasSearched, setHasSearched] = useState(false);
  const search = useMutation({
    mutationFn: (body: { sources: Source[]; query: string; limit_per_source: number }) =>
      api<SearchResponse>("/api/sourcing/search", { method: "POST", json: body }),
    onSettled: () => setHasSearched(true),
  });
  const suggest = useMutation({
    mutationFn: (body: { sources: Source[] }) =>
      api<{ query: string }>(`/api/sourcing/jobs/${jobId}/query/suggest`, {
        method: "POST",
        json: body,
      }),
    onSuccess: (data) => {
      setQuery(data.query);
      if (hasSearched) setHasSearched(false);
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Suggestion failed"),
  });

  function toggle(source: Source) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(source)) next.delete(source);
      else next.add(source);
      return next;
    });
  }

  function onSearch() {
    if (selected.size === 0 || !query.trim()) return;
    search.mutate({
      sources: [...selected],
      query: query.trim(),
      limit_per_source: 5,
    });
  }

  const data = search.data;
  const apiErr = search.error instanceof ApiError ? search.error.detail : null;

  return (
    <div className="space-y-3 mt-4">
      <div className="flex gap-2">
        {SOURCES.map((s) => (
          <Button
            key={s}
            type="button"
            size="sm"
            variant={selected.has(s) ? "default" : "outline"}
            onClick={() => toggle(s)}
          >
            {SOURCE_LABEL[s]}
          </Button>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <Input
          className="flex-1"
          placeholder="senior Rust engineer Berlin"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            // Editing the query invalidates the previous "no results" message
            // so it doesn't linger across distinct searches.
            if (hasSearched) setHasSearched(false);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") onSearch();
          }}
        />
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={() => suggest.mutate({ sources: [...selected] })}
          disabled={selected.size === 0 || suggest.isPending}
          aria-label={suggest.isPending ? "Suggesting query…" : "Suggest query from JD"}
          title="Suggest a query from the job description"
        >
          <Sparkles className={`h-4 w-4 ${suggest.isPending ? "animate-pulse" : ""}`} />
        </Button>
      </div>

      <Button
        onClick={onSearch}
        disabled={selected.size === 0 || !query.trim() || search.isPending}
      >
        {search.isPending ? "Searching…" : "Search"}
      </Button>

      {apiErr && (
        <p className="text-xs text-red-600 border border-red-300 rounded p-2 bg-red-50">
          {apiErr}
        </p>
      )}

      {data?.errors && data.errors.length > 0 && (
        <div className="border border-yellow-400 bg-yellow-50 rounded p-2 space-y-1 text-xs">
          {data.errors.map((e) => (
            <p key={e.source}>
              <span className="font-medium uppercase">{e.source}</span>: {e.reason}
            </p>
          ))}
        </div>
      )}

      {hasSearched && data && data.results.length === 0 && data.errors.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No results found across selected sources.
        </p>
      )}

      <div className="space-y-2">
        {data?.results.map((r) => (
          <SearchResultCard key={`${r.source}:${r.url}`} result={r} jobId={jobId} />
        ))}
      </div>
    </div>
  );
}
