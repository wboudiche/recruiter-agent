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
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import type { JobRead } from "@/hooks/use-jobs";

interface Props {
  job: JobRead;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function EditJobDetailsSheet({ job, open, onOpenChange }: Props) {
  const qc = useQueryClient();
  const [title, setTitle] = useState(job.title);
  const [description, setDescription] = useState(job.description);

  useEffect(() => {
    if (open) {
      setTitle(job.title);
      setDescription(job.description);
    }
  }, [open, job.title, job.description]);

  const save = useMutation({
    mutationFn: () =>
      api<JobRead>(`/api/jobs/${job.id}`, {
        method: "PATCH",
        json: { title, description },
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
  const canSave = (titleDirty || descriptionDirty) && title.trim().length > 0;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-xl flex flex-col">
        <SheetHeader>
          <SheetTitle>Edit job details</SheetTitle>
          <SheetDescription>
            Update the title and the JD. Use the Criteria button to edit
            weighted criteria; this sheet doesn't touch them.
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto space-y-4 py-4">
          <div className="space-y-1">
            <Label htmlFor="job-title">Title</Label>
            <Input
              id="job-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="job-description">Description (JD)</Label>
            <Textarea
              id="job-description"
              rows={16}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
        </div>

        <div className="border-t pt-3 flex justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={save.isPending}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={() => save.mutate()}
            disabled={save.isPending || !canSave}
          >
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
