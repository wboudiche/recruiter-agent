import { useMemo, useState } from "react";
import { Briefcase, ChevronRight, ListChecks, Plus } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useJobs, type JobRead } from "@/hooks/use-jobs";

const STATUS_META: Record<string, { label: string; cls: string }> = {
  open:    { label: "Open",   cls: "stage-extracting" },  // amber → editorial accent
  closed:  { label: "Closed", cls: "stage-rejected" },
  draft:   { label: "Draft",  cls: "stage-sourced" },
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
  const [showClosed, setShowClosed] = useState(false);

  const { closedJobs, visibleJobs } = useMemo(() => {
    const rows = data ?? [];
    const open: JobRead[] = [];
    const closed: JobRead[] = [];
    for (const j of rows) {
      const s = (j.status ?? "open").toLowerCase();
      if (s === "closed") closed.push(j);
      else open.push(j);
    }
    return {
      closedJobs: closed,
      visibleJobs: showClosed ? rows : open,
    };
  }, [data, showClosed]);

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
    <div className="space-y-8">
      <div className="flex items-end justify-between border-b border-border pb-6">
        <div>
          <p className="text-[10px] uppercase tracking-[0.36em] text-[hsl(var(--ed-amber))] mb-2">
            {showClosed ? "All positions" : "Open positions"} ·{" "}
            {visibleJobs.length.toString().padStart(2, "0")}
          </p>
          <h1 className="font-serif italic text-5xl leading-none">Jobs</h1>
          <p className="text-sm text-muted-foreground mt-3 max-w-md">
            Active hiring tracks, ordered by most recent activity.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {closedJobs.length > 0 && (
            <button
              type="button"
              onClick={() => setShowClosed((s) => !s)}
              className="text-[11px] uppercase tracking-[0.22em] text-muted-foreground transition-colors hover:text-foreground"
            >
              {showClosed
                ? "Hide closed"
                : `Show closed (${closedJobs.length})`}
            </button>
          )}
          <Button asChild>
            <Link to="/jobs/new" className="inline-flex items-center gap-1.5">
              <Plus className="h-4 w-4" />
              New job
            </Link>
          </Button>
        </div>
      </div>
      {visibleJobs.length === 0 ? (
        <div className="rounded-xl border border-dashed p-10 text-center text-muted-foreground">
          {showClosed ? (
            <>No jobs match the current filter.</>
          ) : (
            <>
              All jobs are closed.{" "}
              <button
                type="button"
                onClick={() => setShowClosed(true)}
                className="underline hover:text-foreground"
              >
                Show closed ({closedJobs.length})
              </button>
              .
            </>
          )}
        </div>
      ) : (
        <ul className="grid gap-3">
          {visibleJobs.map((job) => (
            <JobCard key={job.id} job={job} />
          ))}
        </ul>
      )}
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
            <span className="mt-1 grid h-9 w-9 shrink-0 place-items-center border border-[hsl(var(--ed-amber)/0.4)] text-[hsl(var(--ed-amber))] transition-colors group-hover:border-[hsl(var(--ed-amber))]">
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
