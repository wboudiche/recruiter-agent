import { useParams } from "react-router-dom";
import { ActionBar } from "@/components/candidate/action-bar";
import { ScoreBreakdown } from "@/components/candidate/score-breakdown";
import { useApplication } from "@/hooks/use-application";
import { useCandidate } from "@/hooks/use-candidate";

export default function ApplicationDetail() {
  const { appId } = useParams<{ appId: string }>();
  const id = Number(appId);
  const application = useApplication(id);
  const candidate = useCandidate(application.data?.candidate_id);

  if (application.isLoading) return <p>Loading…</p>;
  if (application.isError)
    return <p className="text-destructive">Failed to load.</p>;
  if (!application.data) return <p>Not found.</p>;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] gap-6">
      <div className="space-y-6">
        <header className="space-y-2">
          <h2 className="text-xl font-semibold">
            {candidate.data?.full_name ??
              `Candidate #${application.data.candidate_id}`}
          </h2>
          <p className="text-sm text-muted-foreground capitalize">
            {application.data.stage}
          </p>
          {candidate.data?.email && (
            <p className="text-sm text-muted-foreground">{candidate.data.email}</p>
          )}
          <ActionBar
            application={application.data}
            candidateEmail={candidate.data?.email}
          />
        </header>
        <ScoreBreakdown application={application.data} />
      </div>
      <aside>
        <div className="rounded border p-4 text-sm text-muted-foreground">
          Chat panel coming in Plan D
        </div>
      </aside>
    </div>
  );
}
