import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

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
  const add = useMutation({
    mutationFn: () =>
      api(`/api/jobs/${jobId}/candidates`, {
        method: "POST",
        json: { kind: "url", url: result.url },
      }),
    onSuccess: () => {
      toast.success("Added to pipeline");
      qc.invalidateQueries({ queryKey: queryKeys.jobApplications(jobId) });
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
        <Button
          size="sm"
          variant="secondary"
          onClick={() => add.mutate()}
          disabled={add.isPending}
        >
          {add.isPending ? "Adding…" : "Add"}
        </Button>
      </div>
    </div>
  );
}
