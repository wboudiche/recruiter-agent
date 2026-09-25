import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { readOnlyNotice } from "@/lib/read-only-notice";
import type { JobRead } from "@/hooks/use-jobs";
import { useInterviewTemplates, withKind } from "@/hooks/use-interview-templates";

interface Props {
  job: JobRead;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  canWrite?: boolean;
}

export function EditJobDetailsSheet({ job, open, onOpenChange, canWrite = false }: Props) {
  const qc = useQueryClient();
  const [title, setTitle] = useState(job.title);
  const [description, setDescription] = useState(job.description);
  const [defaultTemplate, setDefaultTemplate] = useState<number | null>(
    job.default_interview_template_id ?? null,
  );
  const templates = useInterviewTemplates(false).data ?? [];

  useEffect(() => {
    if (open) {
      setTitle(job.title);
      setDescription(job.description);
      setDefaultTemplate(job.default_interview_template_id ?? null);
    }
  }, [open, job.title, job.description, job.default_interview_template_id]);

  const defaultDirty = defaultTemplate !== (job.default_interview_template_id ?? null);

  const save = useMutation({
    mutationFn: () =>
      api<JobRead>(`/api/jobs/${job.id}`, {
        method: "PATCH",
        json: {
          title,
          description,
          ...(defaultDirty ? { default_interview_template_id: defaultTemplate } : {}),
        },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.job(job.id) });
      qc.invalidateQueries({ queryKey: queryKeys.jobs() });
      toast.success("Job updated");
      onOpenChange(false);
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "Couldn't save");
    },
  });

  const titleDirty = title !== job.title;
  const descriptionDirty = description !== job.description;
  const canSave =
    (titleDirty || descriptionDirty || defaultDirty) && title.trim().length > 0;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-xl flex flex-col">
        <SheetHeader>
          <SheetTitle>{canWrite ? "Edit job details" : "Job details"}</SheetTitle>
          <SheetDescription>
            {canWrite
              ? "Update the title and the JD. Use the Criteria button to edit weighted criteria; this sheet doesn't touch them."
              : readOnlyNotice("edit the title or JD")}
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto space-y-4 py-4">
          <div className="space-y-1">
            <Label htmlFor="job-title">Title</Label>
            <Input
              id="job-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              readOnly={!canWrite}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="job-description">Description (JD)</Label>
            <Textarea
              id="job-description"
              rows={16}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              readOnly={!canWrite}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="job-default-template">Default interview template</Label>
            <Select
              // An archived or unknown default is not in the active list and
              // is treated as none, as the server does at round start.
              value={templates.some((t) => t.id === defaultTemplate) ? String(defaultTemplate) : "none"}
              onValueChange={(v) => setDefaultTemplate(v === "none" ? null : Number(v))}
              disabled={!canWrite}
            >
              <SelectTrigger id="job-default-template" aria-label="Default interview template">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">None — the job's own questions</SelectItem>
                {templates.map((t) => (
                  <SelectItem key={t.id} value={String(t.id)}>{withKind(t.name, t)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="border-t pt-3 flex justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={save.isPending}
          >
            {canWrite ? "Cancel" : "Close"}
          </Button>
          {canWrite && (
            <Button
              type="button"
              onClick={() => save.mutate()}
              disabled={save.isPending || !canSave}
            >
              {save.isPending ? "Saving…" : "Save"}
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
