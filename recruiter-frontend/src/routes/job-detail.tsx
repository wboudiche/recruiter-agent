import { useParams } from "react-router-dom";
import { useJob } from "@/hooks/use-job";
import { useJobApplications } from "@/hooks/use-job-applications";

export default function JobDetail() {
  const { jobId } = useParams<{ jobId: string }>();
  const id = Number(jobId);
  const job = useJob(id);
  const apps = useJobApplications(id);

  if (job.isLoading || apps.isLoading) return <p>Loading…</p>;
  if (job.isError) return <p className="text-destructive">Failed to load job.</p>;
  if (!job.data) return <p>Job not found.</p>;

  return (
    <div className="space-y-4">
      <header>
        <h2 className="text-xl font-semibold">{job.data.title}</h2>
        <p className="text-sm text-muted-foreground">{job.data.status}</p>
      </header>
      <pre className="text-sm whitespace-pre-wrap text-muted-foreground line-clamp-3">
        {job.data.description}
      </pre>
      <p className="text-sm">
        {apps.data?.length ?? 0} candidate
        {(apps.data?.length ?? 0) === 1 ? "" : "s"}
      </p>
    </div>
  );
}
