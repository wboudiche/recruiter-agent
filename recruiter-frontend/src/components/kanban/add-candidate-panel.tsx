import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { SearchTab } from "./search-tab";

interface Props {
  jobId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export function AddCandidatePanel({ jobId, open, onOpenChange }: Props) {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const [content, setContent] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [tab, setTab] = useState<"url" | "upload" | "paste" | "search">("url");

  const submitJson = useMutation({
    mutationFn: (body: object) =>
      api<{ application_id: number }>(`/api/jobs/${jobId}/candidates`, {
        method: "POST",
        json: body,
      }),
    onSuccess: () => {
      toast.success("Candidate added — extracting…");
      queryClient.invalidateQueries({ queryKey: queryKeys.jobApplications(jobId) });
      onOpenChange(false);
      setUrl("");
      setContent("");
    },
    onError: (err: unknown) => {
      const detail = err instanceof ApiError ? err.detail : "Failed to add candidate";
      toast.error(detail);
    },
  });

  const submitFile = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("no file");
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`${BASE_URL}/api/jobs/${jobId}/candidates/upload`, {
        method: "POST",
        body: fd,
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new ApiError(res.status, body.detail ?? res.statusText);
      }
      return (await res.json()) as { application_id: number };
    },
    onSuccess: () => {
      toast.success("Resume uploaded — extracting…");
      queryClient.invalidateQueries({ queryKey: queryKeys.jobApplications(jobId) });
      onOpenChange(false);
      setFile(null);
    },
    onError: (err: unknown) => {
      const detail = err instanceof ApiError ? err.detail : "Failed to upload";
      toast.error(detail);
    },
  });

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (tab === "url") submitJson.mutate({ kind: "url", url });
    else if (tab === "paste") submitJson.mutate({ kind: "paste", content });
    else if (tab === "upload" && file) submitFile.mutate();
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-lg flex flex-col gap-0 overflow-hidden">
        <SheetHeader className="shrink-0 pb-4 border-b">
          <SheetTitle>Add candidate</SheetTitle>
        </SheetHeader>
        <form
          onSubmit={onSubmit}
          className="flex-1 overflow-y-auto space-y-4 pt-4 -mr-2 pr-2"
        >
          <Tabs value={tab} onValueChange={(v) => setTab(v as typeof tab)}>
            <TabsList className="grid w-full grid-cols-4">
              <TabsTrigger value="url">URL</TabsTrigger>
              <TabsTrigger value="upload">Upload</TabsTrigger>
              <TabsTrigger value="paste">Paste</TabsTrigger>
              <TabsTrigger value="search">Search</TabsTrigger>
            </TabsList>
            <TabsContent value="url" className="space-y-2 mt-4">
              <Label htmlFor="cand-url">URL (GitHub, LinkedIn, personal site)</Label>
              <Input
                id="cand-url"
                placeholder="https://github.com/alice"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
            </TabsContent>
            <TabsContent value="upload" className="space-y-2 mt-4">
              <Label htmlFor="cand-file">Resume file (.pdf, .docx)</Label>
              <Input
                id="cand-file"
                type="file"
                accept=".pdf,.docx"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </TabsContent>
            <TabsContent value="paste" className="space-y-2 mt-4">
              <Label htmlFor="cand-content">Profile content</Label>
              <Textarea
                id="cand-content"
                rows={10}
                placeholder="Paste a resume or profile…"
                value={content}
                onChange={(e) => setContent(e.target.value)}
              />
            </TabsContent>
            <TabsContent value="search" className="space-y-2 mt-4">
              <SearchTab jobId={jobId} />
            </TabsContent>
          </Tabs>
          {tab !== "search" && (
            <Button
              type="submit"
              disabled={
                (tab === "url" && !url) ||
                (tab === "paste" && !content) ||
                (tab === "upload" && !file) ||
                submitJson.isPending ||
                submitFile.isPending
              }
            >
              {submitJson.isPending || submitFile.isPending ? "Adding…" : "Add candidate"}
            </Button>
          )}
        </form>
      </SheetContent>
    </Sheet>
  );
}
