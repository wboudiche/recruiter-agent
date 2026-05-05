import { useDroppable } from "@dnd-kit/core";
import { CandidateCard } from "./candidate-card";
import type { Density } from "./kanban-density-toggle";
import { ScoreDistributionStrip } from "./score-distribution-strip";
import type { ApplicationRead } from "@/hooks/use-job-applications";

interface Props {
  title: string;
  stage: ApplicationRead["stage"];
  applications: ApplicationRead[];
  density?: Density;
  selected?: Set<number>;
  onShiftClick?: (id: number) => void;
}

export function KanbanColumn({
  title,
  stage,
  applications,
  density = "comfortable",
  selected,
  onShiftClick,
}: Props) {
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
      {stage === "scored" && applications.length > 0 && (
        <div className="px-2 mb-2">
          <ScoreDistributionStrip applications={applications} />
        </div>
      )}
      <div className={density === "compact" ? "flex-1 space-y-1" : "flex-1 space-y-2"}>
        {applications.map((app) => (
          <CandidateCard
            key={app.id}
            application={app}
            density={density}
            selected={selected?.has(app.id) ?? false}
            onShiftClick={onShiftClick}
          />
        ))}
      </div>
    </div>
  );
}
