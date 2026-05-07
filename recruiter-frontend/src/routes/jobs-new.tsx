// recruiter-frontend/src/routes/jobs-new.tsx
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { zodResolver } from "@hookform/resolvers/zod";
import { useFieldArray, useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { z } from "zod";
import { Plus, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

const Criterion = z.object({
  name: z.string().min(1, "Required"),
  weight: z.coerce.number().min(0).max(1),
  description: z.string().min(1, "Required"),
});

const Schema = z.object({
  title: z.string().min(1, "Title is required").max(255),
  description: z.string().min(1, "Description is required"),
  criteria: z.array(Criterion),
});

type FormValues = z.infer<typeof Schema>;

interface JobReadResp {
  id: number;
}

interface SuggestResponse {
  criteria: Array<{ name: string; weight: number; description: string }>;
}

const DESCRIPTION_MIN_FOR_SUGGEST = 50;

export default function JobsNew() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const form = useForm<FormValues>({
    resolver: zodResolver(Schema),
    defaultValues: { title: "", description: "", criteria: [] },
  });
  const criteria = useFieldArray({ control: form.control, name: "criteria" });
  const description = form.watch("description") ?? "";
  const [confirmOpen, setConfirmOpen] = useState(false);

  const createJob = useMutation({
    mutationFn: (values: FormValues) =>
      api<JobReadResp>("/api/jobs", { method: "POST", json: values }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs() });
      navigate(`/jobs/${data.id}`);
    },
  });

  const suggestCriteria = useMutation({
    mutationFn: (payload: { title: string; description: string }) =>
      api<SuggestResponse>("/api/jobs/criteria/suggest", {
        method: "POST",
        json: payload,
      }),
    onSuccess: (resp) => {
      criteria.replace(resp.criteria);
    },
    onError: () => {
      toast.error("Couldn't suggest criteria — try again.");
    },
  });

  const onSuggestClick = () => {
    if (criteria.fields.length > 0) {
      setConfirmOpen(true);
      return;
    }
    suggestCriteria.mutate({
      title: form.getValues("title"),
      description,
    });
  };

  const onConfirmReplace = () => {
    setConfirmOpen(false);
    suggestCriteria.mutate({
      title: form.getValues("title"),
      description,
    });
  };

  const suggestDisabled =
    description.length < DESCRIPTION_MIN_FOR_SUGGEST || suggestCriteria.isPending;

  return (
    <form
      onSubmit={form.handleSubmit((v) => createJob.mutate(v))}
      className="space-y-6 max-w-3xl"
    >
      <h2 className="text-xl font-semibold">New job</h2>

      <div className="space-y-2">
        <Label htmlFor="title">Title</Label>
        <Input id="title" {...form.register("title")} />
        {form.formState.errors.title && (
          <p className="text-sm text-destructive">{form.formState.errors.title.message}</p>
        )}
      </div>

      <div className="space-y-2">
        <Label htmlFor="description">Description (job description / JD)</Label>
        <Textarea id="description" rows={10} {...form.register("description")} />
        {form.formState.errors.description && (
          <p className="text-sm text-destructive">{form.formState.errors.description.message}</p>
        )}
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label>Custom criteria (optional)</Label>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={suggestDisabled}
              onClick={onSuggestClick}
            >
              <Sparkles className="h-4 w-4 mr-1" />
              {suggestCriteria.isPending ? "Suggesting…" : "Suggest from JD"}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => criteria.append({ name: "", weight: 0.5, description: "" })}
            >
              <Plus className="h-4 w-4 mr-1" />
              Add criterion
            </Button>
          </div>
        </div>
        {criteria.fields.map((field, index) => (
          <div key={field.id} className="grid grid-cols-[1fr_100px_2fr_auto] gap-2 items-start">
            <Input placeholder="Name" {...form.register(`criteria.${index}.name`)} />
            <Input
              placeholder="0.5"
              type="number"
              step="0.1"
              {...form.register(`criteria.${index}.weight`)}
            />
            <Input placeholder="Description" {...form.register(`criteria.${index}.description`)} />
            <Button type="button" variant="ghost" size="icon" onClick={() => criteria.remove(index)}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ))}
      </div>

      <div className="flex gap-2">
        <Button type="submit" disabled={createJob.isPending}>
          {createJob.isPending ? "Creating…" : "Create job"}
        </Button>
        <Button type="button" variant="outline" onClick={() => navigate(-1)}>
          Cancel
        </Button>
      </div>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Replace existing criteria?</DialogTitle>
            <DialogDescription>
              Replace {criteria.fields.length} existing{" "}
              {criteria.fields.length === 1 ? "criterion" : "criteria"} with suggestions from
              the job description? This can't be undone — but you can edit the suggestions
              after.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button type="button" onClick={onConfirmReplace}>
              Replace
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </form>
  );
}
