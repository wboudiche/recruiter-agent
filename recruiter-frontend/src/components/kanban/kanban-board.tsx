import { useMemo } from "react";
import {
  DndContext,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { KanbanColumn } from "./kanban-column";
import type { ApplicationRead } from "@/hooks/use-job-applications";

const COLUMN_ORDER: { stage: ApplicationRead["stage"]; title: string }[] = [
  { stage: "extracting", title: "Extracting" },
  { stage: "scored", title: "Scored" },
  { stage: "validated", title: "Validated" },
  { stage: "invited", title: "Invited" },
  { stage: "scheduled", title: "Scheduled" },
];

interface Props {
  applications: ApplicationRead[];
  jobId?: number;
  showRejected?: boolean;
}

export function KanbanBoard({ applications, jobId, showRejected = false }: Props) {
  const sensors = useSensors(useSensor(PointerSensor), useSensor(KeyboardSensor));
  const queryClient = useQueryClient();

  const grouped = useMemo(() => {
    const m = new Map<string, ApplicationRead[]>();
    for (const a of applications) {
      if (a.stage === "rejected" && !showRejected) continue;
      const list = m.get(a.stage) ?? [];
      list.push(a);
      m.set(a.stage, list);
    }
    return m;
  }, [applications, showRejected]);

  const columns = [...COLUMN_ORDER];
  if (showRejected) columns.push({ stage: "rejected", title: "Rejected" });

  const patch = useMutation({
    mutationFn: ({ id, stage }: { id: number; stage: string }) =>
      api(`/api/applications/${id}`, { method: "PATCH", json: { stage } }),
    onSuccess: () => {
      if (jobId !== undefined)
        queryClient.invalidateQueries({
          queryKey: queryKeys.jobApplications(jobId),
        });
    },
    onError: (err) => {
      const detail = err instanceof ApiError ? err.detail : "Move failed";
      toast.error(detail);
    },
  });

  function onDragEnd(event: DragEndEvent) {
    if (!event.over || !event.active) return;
    const targetStage = (event.over.data.current as { stage: string } | undefined)
      ?.stage;
    const fromStage = (
      event.active.data.current as { currentStage: string } | undefined
    )?.currentStage;
    const id = (event.active.data.current as { applicationId: number } | undefined)
      ?.applicationId;
    if (!targetStage || !fromStage || !id || targetStage === fromStage) return;

    // UI guards (server enforces too).
    // Allow: scored→validated, validated→scored (unvalidate), any→rejected.
    const allowed =
      (fromStage === "scored" && targetStage === "validated") ||
      (fromStage === "validated" && targetStage === "scored") ||
      targetStage === "rejected";
    if (!allowed) {
      toast.error(`Cannot move from ${fromStage} to ${targetStage}`);
      return;
    }
    patch.mutate({ id, stage: targetStage });
  }

  return (
    <DndContext sensors={sensors} onDragEnd={onDragEnd}>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        {columns.map((c) => (
          <KanbanColumn
            key={c.stage}
            title={c.title}
            stage={c.stage}
            applications={grouped.get(c.stage) ?? []}
          />
        ))}
      </div>
    </DndContext>
  );
}
