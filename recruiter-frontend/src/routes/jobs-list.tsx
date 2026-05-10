import { Briefcase, ChevronRight, ListChecks, Plus } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useJobs, type JobRead } from "@/hooks/use-jobs";

const STATUS_META: Record<string, { label: string; cls: string }> = {
  open:    { label: "Open",   cls: "stage-validated" },
  closed:  { label: "Closed", cls: "stage-rejected" },
  draft:   { label: "Draft",  cls: "stage-extracting" },
};

function formatRelative(iso: string): string {
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  const days = Math.floor(diffMs / 86_400_000);
  if (days < 1) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days}d ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}

export default function JobsList() {
  const { data, isLoading, isError } = useJobs();

  if (isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (isError) return <p className="text-destructive">Failed to load jobs.</p>;
  if (!data?.length) {
    return (
      <div className="space-y-6">
        <h2 className="text-2xl font-semibold tracking-tight">Jobs</h2>
        <div className="rounded-xl border border-dashed p-12 text-center">
          <Briefcase className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
          <p className="text-muted-foreground mb-4">No jobs yet.</p>
          <Button asChild>
            <Link to="/jobs/new" className="inline-flex items-center gap-1.5">
              <Plus className="h-4 w-4" />
              Create your first job
            </Link>
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Jobs</h2>
          <p className="text-sm text-muted-foreground">
            {data.length} {data.length === 1 ? "job" : "jobs"} active
          </p>
        </div>
        <Button asChild>
          <Link to="/jobs/new" className="inline-flex items-center gap-1.5">
            <Plus className="h-4 w-4" />
            New job
          </Link>
        </Button>
      </div>
      <ul className="grid gap-3">
        {data.map((job) => (
          <JobCard key={job.id} job={job} />
        ))}
      </ul>
    </div>
  );
}

function JobCard({ job }: { job: JobRead }) {
  const statusKey = (job.status ?? "open").toLowerCase();
  const status = STATUS_META[statusKey] ?? STATUS_META.open;
  const criteriaCount = job.criteria?.length ?? 0;
  return (
    <li>
      <Link
        to={`/jobs/${job.id}`}
        className="group block rounded-xl border bg-card p-5 transition-all hover:border-primary/40 hover:shadow-[0_0_0_4px_hsl(var(--primary)/0.08)]"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3 min-w-0 flex-1">
            <span className="mt-1 grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-violet-500/15 to-fuchsia-500/15 text-violet-500 group-hover:from-violet-500/25 group-hover:to-fuchsia-500/25 transition-colors">
              <Briefcase className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="font-semibold truncate">{job.title}</h3>
                <span className={`stage-pill ${status.cls}`}>{status.label}</span>
              </div>
              <p className="text-sm text-muted-foreground line-clamp-2 mt-1">
                {job.description}
              </p>
              <div className="flex items-center gap-3 mt-3 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  <ListChecks className="h-3.5 w-3.5" />
                  {criteriaCount} {criteriaCount === 1 ? "criterion" : "criteria"}
                </span>
                <span aria-hidden>·</span>
                <span>updated {formatRelative(job.updated_at)}</span>
              </div>
            </div>
          </div>
          <ChevronRight className="h-5 w-5 text-muted-foreground/40 group-hover:text-primary group-hover:translate-x-0.5 transition-all shrink-0 mt-2" />
        </div>
      </Link>
    </li>
  );
}
