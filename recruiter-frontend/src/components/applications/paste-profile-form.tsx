import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

interface Props {
  applicationId: number;
  sourceUrl?: string | null;
}

export function PasteProfileForm({ applicationId, sourceUrl }: Props) {
  const [content, setContent] = useState("");
  const qc = useQueryClient();
  const submit = useMutation({
    mutationFn: () =>
      api(`/api/applications/${applicationId}/paste`, {
        method: "POST",
        json: { content },
      }),
    onSuccess: () => {
      toast.success("Profile content received — extracting…");
      qc.invalidateQueries({
        queryKey: queryKeys.application(applicationId),
      });
      setContent("");
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "Submit failed");
    },
  });

  return (
    <div className="p-4 space-y-3">
      <div className="space-y-1">
        <h3 className="font-medium text-sm">Paste profile content</h3>
        <p className="text-xs text-muted-foreground">
          LinkedIn forbids automated scraping. Open the profile
          {sourceUrl ? (
            <>
              {" "}
              at{" "}
              <a
                href={sourceUrl}
                target="_blank"
                rel="noreferrer"
                className="underline"
              >
                {sourceUrl}
              </a>
            </>
          ) : null}
          , copy the content, and paste it below.
        </p>
      </div>
      <Textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder="Paste the candidate's profile here…"
        rows={12}
        className="text-xs font-mono"
      />
      <Button
        onClick={() => submit.mutate()}
        disabled={!content.trim() || submit.isPending}
        size="sm"
      >
        {submit.isPending ? "Submitting…" : "Submit"}
      </Button>
    </div>
  );
}
