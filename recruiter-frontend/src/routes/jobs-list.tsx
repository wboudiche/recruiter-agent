import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useJobs } from "@/hooks/use-jobs";

export default function JobsList() {
  const { data, isLoading, isError } = useJobs();

  if (isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (isError) return <p className="text-destructive">Failed to load jobs.</p>;
  if (!data?.length) {
    return (
      <div className="space-y-4">
        <h2 className="text-lg font-medium">Jobs</h2>
        <p className="text-muted-foreground">No jobs yet.</p>
        <Button asChild>
          <Link to="/jobs/new">Create your first job</Link>
        </Button>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium">Jobs</h2>
        <Button asChild>
          <Link to="/jobs/new">New job</Link>
        </Button>
      </div>
      <ul className="space-y-2">
        {data.map((job) => (
          <li key={job.id} className="rounded border p-4 hover:bg-accent">
            <Link to={`/jobs/${job.id}`} className="block">
              <h3 className="font-medium">{job.title}</h3>
              <p className="text-sm text-muted-foreground line-clamp-2">{job.description}</p>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
