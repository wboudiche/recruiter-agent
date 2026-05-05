import { useState } from "react";
import { useParams } from "react-router-dom";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AddCandidatePanel } from "@/components/kanban/add-candidate-panel";
import { KanbanBoard } from "@/components/kanban/kanban-board";
import {
  KanbanDensityToggle,
  type Density,
} from "@/components/kanban/kanban-density-toggle";
import { useJob } from "@/hooks/use-job";
import { useJobApplications } from "@/hooks/use-job-applications";

const DENSITY_KEY = "kanban.density";

function readDensity(): Density {
  try {
    const v = localStorage.getItem(DENSITY_KEY);
    return v === "compact" ? "compact" : "comfortable";
  } catch {
    return "comfortable";
  }
}

export default function JobDetail() {
  const { jobId } = useParams<{ jobId: string }>();
  const id = Number(jobId);
  const job = useJob(id);
  const apps = useJobApplications(id);
  const [showRejected, setShowRejected] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [density, setDensity] = useState<Density>(readDensity);

  function changeDensity(d: Density) {
    setDensity(d);
    try { localStorage.setItem(DENSITY_KEY, d); } catch { /* ignore */ }
  }

  if (job.isLoading || apps.isLoading) return <p>Loading…</p>;
  if (job.isError) return <p className="text-destructive">Failed to load job.</p>;
  if (!job.data) return <p>Job not found.</p>;

  return (
    <div className="space-y-4">
      <header className="flex items-baseline justify-between">
        <div>
          <h2 className="text-xl font-semibold">{job.data.title}</h2>
          <p className="text-sm text-muted-foreground">{job.data.status}</p>
        </div>
        <div className="flex gap-2 items-center">
          <KanbanDensityToggle value={density} onChange={changeDensity} />
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowRejected((s) => !s)}
          >
            {showRejected ? "Hide rejected" : "Show rejected"}
          </Button>
          <Button size="sm" onClick={() => setAddOpen(true)}>
            <Plus className="h-4 w-4 mr-1" />
            Add candidate
          </Button>
        </div>
      </header>
      <KanbanBoard
        applications={apps.data ?? []}
        jobId={id}
        showRejected={showRejected}
        density={density}
      />
      <AddCandidatePanel jobId={id} open={addOpen} onOpenChange={setAddOpen} />
    </div>
  );
}
