import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { ActionBar } from "@/components/candidate/action-bar";
import { CandidateProfile } from "@/components/candidate/candidate-profile";
import { ChatPanel } from "@/components/applications/chat-panel";
import { PasteProfileForm } from "@/components/applications/paste-profile-form";
import {
  EnrichmentSection,
  type Bundle as EnrichmentBundle,
} from "@/components/candidate/enrichment-section";
import { RejectionBanner } from "@/components/candidate/rejection-banner";
import { ScoreBreakdown } from "@/components/candidate/score-breakdown";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Spinner } from "@/components/ui/spinner";
import { pushRecentApp } from "@/components/command-palette/command-palette-context";
import { useApplication } from "@/hooks/use-application";
import { useCandidate } from "@/hooks/use-candidate";
import { useJob } from "@/hooks/use-job";

export default function ApplicationDetail() {
  const { appId } = useParams<{ appId: string }>();
  const id = Number(appId);
  const application = useApplication(id);
  const candidate = useCandidate(application.data?.candidate_id);
  // Job is only needed for the breadcrumb. We pass `enabled` via the
  // application's job_id so the query waits for the application fetch.
  const job = useJob(application.data?.job_id ?? Number.NaN);

  useEffect(() => {
    if (application.data && candidate.data) {
      pushRecentApp({
        id: application.data.id,
        name: candidate.data.full_name ?? `Candidate #${application.data.candidate_id}`,
        ts: Date.now(),
      });
    }
  }, [application.data, candidate.data]);

  if (application.isLoading) return <p>Loading…</p>;
  if (application.isError)
    return <p className="text-destructive">Failed to load.</p>;
  if (!application.data) return <p>Not found.</p>;

  const candidateName =
    candidate.data?.full_name ?? `Candidate #${application.data.candidate_id}`;
  const jobTitle = job.data?.title ?? `Job #${application.data.job_id}`;

  return (
    <div className="flex flex-col gap-4 h-[calc(100vh-6.5rem)]">
      <Breadcrumb
        items={[
          { label: "Jobs", to: "/jobs" },
          { label: jobTitle, to: `/jobs/${application.data.job_id}` },
          { label: candidateName },
        ]}
      />
      <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] gap-6 flex-1 min-h-0">
      <div className="space-y-6 overflow-y-auto pr-2">
        {candidate.data && <CandidateProfile candidate={candidate.data} />}
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
            stage:
          </span>
          <span className="text-sm font-medium capitalize">
            {application.data.awaiting_paste
              ? "needs paste"
              : application.data.stage}
          </span>
          <div className="ml-auto">
            <ActionBar
              application={application.data}
              candidateEmail={candidate.data?.email}
            />
          </div>
        </div>
        {application.data.awaiting_paste && (
          <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-4 text-sm">
            <p className="font-medium text-amber-200">
              Auto-extraction couldn’t fetch this profile.
            </p>
            <p className="text-muted-foreground mt-1">
              LinkedIn requires either an Apify API token (Settings → Sourcing) or a
              connected LinkedIn cookie/credentials to scrape automatically. Until
              one is configured, paste the profile manually using the form on the
              right — open the source URL, copy the page, and submit.
            </p>
          </div>
        )}
        <RejectionBanner application={application.data} />
        <ScoreBreakdown application={application.data} />
        <EnrichmentSection
          applicationId={id}
          enrichment={
            (application.data.enrichment as EnrichmentBundle | null) ?? null
          }
        />
      </div>
      <aside className="rounded border overflow-hidden">
        {application.data.awaiting_paste ? (
          <PasteProfileForm
            applicationId={id}
            sourceUrl={candidate.data?.source_url}
          />
        ) : application.data.stage === "extracting"
          || application.data.stage === "enriching" ? (
          <ExtractionLoader
            stage={application.data.stage}
            sourceUrl={candidate.data?.source_url ?? null}
          />
        ) : (
          <ChatPanel applicationId={id} jobId={application.data.job_id} />
        )}
      </aside>
      </div>
    </div>
  );
}


function ExtractionLoader({
  stage,
  sourceUrl,
}: {
  stage: "extracting" | "enriching";
  sourceUrl: string | null;
}) {
  const host = (() => {
    try {
      return sourceUrl ? new URL(sourceUrl).hostname.replace(/^www\./, "") : null;
    } catch {
      return null;
    }
  })();
  const headline =
    stage === "enriching"
      ? "Enriching profile…"
      : `Extracting profile${host ? ` from ${host}` : ""}…`;
  const subline =
    stage === "enriching"
      ? "Web context → skills synthesis → scoring"
      : "Auto-fetch → LLM extraction → scoring";
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
      <Spinner size={32} className="text-[hsl(var(--ed-amber))]" />
      <div className="space-y-2">
        <p className="font-serif italic text-base text-foreground">{headline}</p>
        <p className="text-xs uppercase tracking-[0.22em] text-muted-foreground">
          {subline}
        </p>
        <p className="text-xs text-muted-foreground max-w-xs mx-auto leading-relaxed">
          Usually takes 20–30 seconds. The card moves to <em>Scored</em>
          automatically — no need to refresh.
        </p>
      </div>
    </div>
  );
}
