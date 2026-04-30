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
  showRejected?: boolean;
}

export function KanbanBoard({ applications, showRejected = false }: Props) {
  const grouped = new Map<string, ApplicationRead[]>();
  for (const a of applications) {
    if (a.stage === "rejected" && !showRejected) continue;
    const list = grouped.get(a.stage) ?? [];
    list.push(a);
    grouped.set(a.stage, list);
  }
  const columns = [...COLUMN_ORDER];
  if (showRejected) columns.push({ stage: "rejected", title: "Rejected" });

  return (
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
  );
}
