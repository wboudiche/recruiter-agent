import { useDroppable } from "@dnd-kit/core";
import {
  Calendar,
  CheckCircle2,
  ClipboardEdit,
  Mail,
  Sparkles,
  Star,
  XCircle,
} from "lucide-react";
import type { ReactNode } from "react";
import { CandidateCard } from "./candidate-card";
import type { Density } from "./kanban-density-toggle";
import { ScoreDistributionStrip } from "./score-distribution-strip";
import type { ApplicationRead } from "@/hooks/use-job-applications";
import type { CandidateRead } from "@/hooks/use-candidate";

interface Props {
  title: string;
  stage: ApplicationRead["stage"];
  applications: ApplicationRead[];
  candidates?: Map<number, CandidateRead>;
  density?: Density;
  selected?: Set<number>;
  onShiftClick?: (id: number) => void;
}

const STAGE_META: Record<ApplicationRead["stage"], { icon: ReactNode; cls: string }> = {
  sourced:    { icon: <Sparkles      className="h-3.5 w-3.5" />, cls: "stage-sourced" },
  extracting: { icon: <ClipboardEdit className="h-3.5 w-3.5" />, cls: "stage-extracting" },
  // Enriching is a brief mid-pipeline phase; the kanban board doesn't
  // expose its own column, but type completeness requires an entry. We
  // reuse extracting's styling because they belong to the same "still
  // working on it" bucket from a user's POV.
  enriching:  { icon: <ClipboardEdit className="h-3.5 w-3.5" />, cls: "stage-extracting" },
  scored:     { icon: <Star          className="h-3.5 w-3.5" />, cls: "stage-scored" },
  validated:  { icon: <CheckCircle2  className="h-3.5 w-3.5" />, cls: "stage-validated" },
  invited:    { icon: <Mail          className="h-3.5 w-3.5" />, cls: "stage-invited" },
  scheduled:  { icon: <Calendar      className="h-3.5 w-3.5" />, cls: "stage-scheduled" },
  rejected:   { icon: <XCircle       className="h-3.5 w-3.5" />, cls: "stage-rejected" },
};

export function KanbanColumn({
  title,
  stage,
  applications,
  candidates,
  density = "comfortable",
  selected,
  onShiftClick,
}: Props) {
  const { setNodeRef, isOver } = useDroppable({
    id: `col-${stage}`,
    data: { stage },
  });
  const meta = STAGE_META[stage];
  return (
    <div
      ref={setNodeRef}
      className={`flex flex-col rounded-lg border bg-muted/20 p-2 min-h-[200px] transition-colors ${isOver ? "ring-2 ring-primary border-primary/40" : ""}`}
    >
      <header className="px-2 py-1 mb-2 flex items-center justify-between">
        <span className={`stage-pill ${meta.cls}`}>
          {meta.icon}
          {title}
        </span>
        <span className="text-xs font-mono text-muted-foreground tabular-nums">
          {applications.length}
        </span>
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
            candidateName={candidates?.get(app.candidate_id)?.full_name ?? undefined}
            density={density}
            selected={selected?.has(app.id) ?? false}
            onShiftClick={onShiftClick}
          />
        ))}
      </div>
    </div>
  );
}
