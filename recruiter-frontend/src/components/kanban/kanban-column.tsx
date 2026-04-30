import { useDroppable } from "@dnd-kit/core";
import { CandidateCard } from "./candidate-card";
import type { ApplicationRead } from "@/hooks/use-job-applications";

interface Props {
  title: string;
  stage: ApplicationRead["stage"];
  applications: ApplicationRead[];
}

export function KanbanColumn({ title, stage, applications }: Props) {
  const { setNodeRef, isOver } = useDroppable({
    id: `col-${stage}`,
    data: { stage },
  });
  return (
    <div
      ref={setNodeRef}
      className={`flex flex-col rounded-md border bg-muted/30 p-2 min-h-[200px] ${isOver ? "ring-2 ring-primary" : ""}`}
    >
      <header className="px-2 py-1 mb-2 flex items-center justify-between">
        <h3 className="text-sm font-medium">{title}</h3>
        <span className="text-xs text-muted-foreground">{applications.length}</span>
      </header>
      <div className="flex-1 space-y-2">
        {applications.map((app) => (
          <CandidateCard key={app.id} application={app} />
        ))}
      </div>
    </div>
  );
}
