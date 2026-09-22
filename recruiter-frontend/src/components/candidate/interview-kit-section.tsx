import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useInterviewers } from "@/hooks/use-interviewers";
import { useInterviewTemplates } from "@/hooks/use-interview-templates";
import {
  type SheetRead, type TrackRead, sheetHasContent, useInterviewKit, useTrackMutations,
} from "@/hooks/use-interview-kit";
import { AddTrackDialog, type TrackOption } from "./add-track-dialog";
import { TrackKitView, errorMessage } from "./track-kit-view";

interface Props {
  applicationId: number;
  canWrite: boolean;
  /** Which round is in progress. Labelled only past the first, where a
   *  reset of every sheet is otherwise indistinguishable from a round
   *  that never happened. */
  interviewRound?: number;
  /** The application's stage: tracks are added and removed only while the
   *  interview is scheduled. */
  stage?: string;
}

const trackLabel = (t: TrackRead) => t.template_name ?? "No template";

export function InterviewKitSection({ applicationId, canWrite, interviewRound, stage }: Props) {
  const { tracks, sheets, isLoading, isError, refetch, generate } =
    useInterviewKit(applicationId);
  // Warm the cache TrackKitView's own useCurrentUser/useInterviewers read,
  // in parallel with the kit fetch above rather than after it. TrackKitView
  // only mounts once a track exists, so without this, those two queries
  // would start a render later than the kit query — a real, if brief,
  // fetch waterfall (and identity-dependent UI, e.g. "is this my sheet?",
  // would lag a tick behind the kit becoming visible) that didn't exist
  // when everything lived in one component. Same queryKey, so this is a
  // subscribe, never a second request.
  useCurrentUser();
  useInterviewers(applicationId);
  const { addTrack, removeTrack } = useTrackMutations(applicationId);
  const canChangeTracks = canWrite && stage === "scheduled";
  const templates = useInterviewTemplates(false, canChangeTracks).data ?? [];
  const [addOpen, setAddOpen] = useState(false);
  const [active, setActive] = useState<string | null>(null);

  if (isLoading) return null;

  if (isError) {
    return (
      <section className="space-y-2">
        <h3 className="text-lg font-semibold">Interview kit</h3>
        <p className="text-xs border border-danger-line bg-danger-soft text-danger rounded p-2">
          Couldn't load the interview kit.
        </p>
        <Button variant="outline" onClick={() => refetch()}>Retry</Button>
      </section>
    );
  }

  if (tracks.length === 0) {
    return (
      <section className="space-y-2">
        <h3 className="text-lg font-semibold">Interview kit</h3>
        {canWrite && (
          <Button
            onClick={() =>
              generate.mutate(undefined, {
                onError: (err) =>
                  toast.error(errorMessage(err, "Couldn't start generation")),
              })}
            disabled={generate.isPending}
          >
            Generate interview kit
          </Button>
        )}
      </section>
    );
  }

  const liveRound = interviewRound ?? 1;
  const liveSheets = (track: string): SheetRead[] =>
    sheets.filter((s) => (s.round ?? 1) === liveRound && (s.track ?? "default") === track);

  // Tracks this round does not have yet: every active template not in use,
  // and the no-template track when the round lacks it.
  const used = new Set(tracks.map((t) => t.template_id));
  const options: TrackOption[] = [
    ...(used.has(null) ? [] : [{ templateId: null, label: "No template" }]),
    ...templates.filter((t) => !used.has(t.id)).map((t) => ({ templateId: t.id, label: t.name })),
  ];
  const addButton = canChangeTracks && options.length > 0 && (
    <Button variant="outline" size="sm" onClick={() => setAddOpen(true)}>+ Add track</Button>
  );
  const addDialog = (
    <AddTrackDialog
      open={addOpen}
      onOpenChange={setAddOpen}
      options={options}
      pending={addTrack.isPending}
      onConfirm={(templateId) =>
        addTrack.mutate(templateId, {
          onSuccess: () => setAddOpen(false),
          onError: (err) => toast.error(errorMessage(err, "Couldn't add the track")),
        })}
    />
  );

  if (tracks.length === 1) {
    const only = tracks[0];
    const view = (
      <TrackKitView
        applicationId={applicationId}
        canWrite={canWrite}
        interviewRound={interviewRound}
        track={null}
        kit={only.kit}
        templateName={only.template_name}
        sheets={sheets}
      />
    );
    // Nothing to add (no templates, or all in use): exactly today's view.
    if (!addButton) return view;
    return (
      <div className="space-y-3">
        {view}
        {addButton}
        {addDialog}
      </div>
    );
  }

  // A removed track's tab falls back to the first one.
  const current = tracks.some((t) => t.track === active) ? (active as string) : tracks[0].track;

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-lg font-semibold">
          Interview kit
          {liveRound > 1 && (
            <span className="ml-2 text-xs font-normal uppercase tracking-[0.18em] text-muted-foreground">
              Round {liveRound}
            </span>
          )}
        </h3>
        {addButton}
      </div>
      <Tabs value={current} onValueChange={setActive}>
        <TabsList>
          {tracks.map((t) => {
            const panel = liveSheets(t.track);
            const done = panel.filter((s) => s.submitted_at).length;
            return (
              <TabsTrigger key={t.track} value={t.track}>
                {trackLabel(t)}
                <span className="ml-2 text-xs text-muted-foreground">
                  {t.kit.status === "generating" ? "…"
                    : panel.length === 0 ? "no interviewers" : `${done}/${panel.length}`}
                </span>
              </TabsTrigger>
            );
          })}
        </TabsList>
        {tracks.map((t) => {
          const written = liveSheets(t.track)
            .some((s) => s.submitted_at || sheetHasContent(s.sheet));
          return (
            // Every track stays mounted, hidden when inactive, so unsaved
            // edits in one track survive switching to another.
            <TabsContent key={t.track} value={t.track} forceMount
              className="space-y-3 data-[state=inactive]:hidden">
              {canChangeTracks && (
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-auto px-2 py-1 text-xs"
                    aria-label={`Remove track ${trackLabel(t)}`}
                    disabled={written || removeTrack.isPending}
                    onClick={() => removeTrack.mutate(t.track, {
                      onError: (err) =>
                        toast.error(errorMessage(err, "Couldn't remove the track")),
                    })}
                  >
                    Remove track
                  </Button>
                  {written && (
                    <span className="text-xs text-muted-foreground">
                      Someone on this track has written feedback.
                    </span>
                  )}
                </div>
              )}
              <TrackKitView
                applicationId={applicationId}
                canWrite={canWrite}
                interviewRound={interviewRound}
                track={t.track}
                kit={t.kit}
                templateName={t.template_name}
                sheets={sheets}
                showHeader={false}
              />
            </TabsContent>
          );
        })}
      </Tabs>
      {addDialog}
    </section>
  );
}
