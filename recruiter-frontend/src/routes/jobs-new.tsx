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
  enrichment_consent: z.boolean().default(false),
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
    defaultValues: { title: "", description: "", criteria: [], enrichment_consent: false },
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
        <Textarea
          id="description"
          {...form.register("description")}
          // Auto-grow up to ~32rem (~half a tall screen), then scroll.
          // Tailwind `field-sizing-content` is widely supported in
          // Chrome/Edge/Safari 17+ (also in your dev Chromium); on
          // older browsers we still have a generous min-height so the
          // box never feels cramped, with vertical resize as a fallback.
          className="min-h-[14rem] max-h-[32rem] resize-y leading-relaxed [field-sizing:content]"
        />
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
        {criteria.fields.length > 0 && (
          <div className="flex items-center justify-end">
            <TotalWeightIndicator
              total={criteria.fields.reduce(
                (sum, _, i) => sum + Number(form.watch(`criteria.${i}.weight`) ?? 0),
                0,
              )}
            />
          </div>
        )}
        {criteria.fields.map((field, index) => (
          <div
            key={field.id}
            className="space-y-2 border border-border p-3"
          >
            <div className="grid grid-cols-[1fr_110px_auto] gap-2 items-end">
              <div className="space-y-1">
                <Label htmlFor={`criteria-name-${index}`}>Name</Label>
                <Input
                  id={`criteria-name-${index}`}
                  placeholder="e.g. PyTorch expertise"
                  {...form.register(`criteria.${index}.name`)}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor={`criteria-weight-${index}`}>Weight</Label>
                <Input
                  id={`criteria-weight-${index}`}
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  placeholder="0.25"
                  {...form.register(`criteria.${index}.weight`)}
                />
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => criteria.remove(index)}
                aria-label="Remove criterion"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
            <div className="space-y-1">
              <Label htmlFor={`criteria-desc-${index}`}>Description</Label>
              <Textarea
                id={`criteria-desc-${index}`}
                rows={2}
                placeholder="What evidence in a candidate's profile should match this criterion?"
                {...form.register(`criteria.${index}.description`)}
                className="leading-relaxed"
              />
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-start gap-2">
        <input
          type="checkbox"
          id="enrichment-consent"
          className="mt-1"
          {...form.register("enrichment_consent")}
        />
        <Label htmlFor="enrichment-consent" className="text-sm leading-snug font-normal">
          Process the candidate's public technical and social presence for scoring.
          Required where applicable law (e.g., GDPR Art. 6 + 9) demands lawful basis.
        </Label>
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


function TotalWeightIndicator({ total }: { total: number }) {
  // Backend normalises whatever weights we send, but surfacing the
  // running total at all helps the user balance their criteria as they
  // tweak them. Amber tint when the total drifts noticeably from 1.0.
  const off = Math.abs(total - 1) > 0.01;
  return (
    <span
      className={`text-xs ${
        off ? "text-[hsl(var(--ed-amber))]" : "text-muted-foreground"
      }`}
    >
      Total weight: {total.toFixed(2)}
    </span>
  );
}
