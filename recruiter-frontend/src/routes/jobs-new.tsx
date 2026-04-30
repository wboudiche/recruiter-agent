import { useMutation, useQueryClient } from "@tanstack/react-query";
import { zodResolver } from "@hookform/resolvers/zod";
import { useFieldArray, useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { z } from "zod";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
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

export default function JobsNew() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const form = useForm<FormValues>({
    resolver: zodResolver(Schema),
    defaultValues: { title: "", description: "", criteria: [] },
  });
  const criteria = useFieldArray({ control: form.control, name: "criteria" });

  const createJob = useMutation({
    mutationFn: (values: FormValues) =>
      api<JobReadResp>("/api/jobs", { method: "POST", json: values }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs() });
      navigate(`/jobs/${data.id}`);
    },
  });

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
    </form>
  );
}
