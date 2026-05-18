import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Sparkles, Trash2 } from "lucide-react";
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
import type { CriteriaItem, JobRead } from "@/hooks/use-jobs";

interface Props {
  job: JobRead;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface SuggestResponse {
  criteria: CriteriaItem[];
}

const DESCRIPTION_MIN_FOR_SUGGEST = 50;

export function EditCriteriaSheet({ job, open, onOpenChange }: Props) {
  const qc = useQueryClient();
  // Editable working copy of the criteria. Initialised from the job when
  // the sheet opens, persisted on Save.
  const [items, setItems] = useState<CriteriaItem[]>(job.criteria ?? []);

  useEffect(() => {
    if (open) setItems(job.criteria ?? []);
  }, [open, job.criteria]);

  const save = useMutation({
    mutationFn: () =>
      api<JobRead>(`/api/jobs/${job.id}`, {
        method: "PATCH",
        json: { criteria: items },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.job(job.id) });
      qc.invalidateQueries({ queryKey: queryKeys.jobs() });
      toast.success("Criteria saved");
      onOpenChange(false);
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "Save failed");
    },
  });

  const suggest = useMutation({
    mutationFn: () =>
      api<SuggestResponse>("/api/jobs/criteria/suggest", {
        method: "POST",
        json: { title: job.title, description: job.description },
      }),
    onSuccess: (resp) => {
      setItems(resp.criteria);
      toast.success("Suggestions loaded — review and save");
    },
    onError: () => toast.error("Couldn't suggest criteria — try again."),
  });

  const totalWeight = items.reduce((s, c) => s + (Number(c.weight) || 0), 0);
  const totalOff = Math.abs(totalWeight - 1) > 0.01;
  const suggestDisabled =
    (job.description ?? "").length < DESCRIPTION_MIN_FOR_SUGGEST || suggest.isPending;

  function update(i: number, patch: Partial<CriteriaItem>) {
    setItems((prev) => prev.map((it, idx) => (idx === i ? { ...it, ...patch } : it)));
  }
  function remove(i: number) {
    setItems((prev) => prev.filter((_, idx) => idx !== i));
  }
  function add() {
    setItems((prev) => [...prev, { name: "", weight: 0.25, description: "" }]);
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-xl flex flex-col">
        <SheetHeader>
          <SheetTitle>Edit criteria</SheetTitle>
          <SheetDescription>
            Each candidate's score is a weighted average across these criteria.
            Weights should sum to 1.0 — if they don't, the backend will normalise them.
          </SheetDescription>
        </SheetHeader>

        <div className="flex items-center gap-2 py-3 border-b">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={suggestDisabled}
            onClick={() => suggest.mutate()}
          >
            <Sparkles className="h-4 w-4 mr-1" />
            {suggest.isPending ? "Suggesting…" : "Suggest from JD"}
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={add}>
            <Plus className="h-4 w-4 mr-1" />
            Add criterion
          </Button>
          <span
            className={`ml-auto text-xs ${totalOff ? "text-[hsl(var(--ed-amber))]" : "text-muted-foreground"}`}
          >
            Total weight: {totalWeight.toFixed(2)}
          </span>
        </div>

        <div className="flex-1 overflow-y-auto space-y-4 py-4">
          {items.length === 0 && (
            <p className="text-sm text-muted-foreground italic">
              No criteria yet. Use <em>Suggest from JD</em> or <em>Add criterion</em> to start.
            </p>
          )}
          {items.map((it, idx) => (
            <div
              key={idx}
              className="space-y-2 border border-border p-3"
            >
              <div className="grid grid-cols-[1fr_110px_auto] gap-2 items-end">
                <div className="space-y-1">
                  <Label htmlFor={`name-${idx}`}>Name</Label>
                  <Input
                    id={`name-${idx}`}
                    value={it.name}
                    onChange={(e) => update(idx, { name: e.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor={`weight-${idx}`}>Weight</Label>
                  <Input
                    id={`weight-${idx}`}
                    type="number"
                    min={0}
                    max={1}
                    step={0.05}
                    value={it.weight}
                    onChange={(e) =>
                      update(idx, { weight: Number(e.target.value) })
                    }
                  />
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => remove(idx)}
                  aria-label="Remove criterion"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
              <div className="space-y-1">
                <Label htmlFor={`desc-${idx}`}>Description</Label>
                <Textarea
                  id={`desc-${idx}`}
                  rows={2}
                  value={it.description}
                  onChange={(e) =>
                    update(idx, { description: e.target.value })
                  }
                />
              </div>
            </div>
          ))}
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
          <Button type="button" onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
