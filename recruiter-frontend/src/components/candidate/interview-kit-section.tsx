import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useInterviewers } from "@/hooks/use-interviewers";
import { useInterviewKit } from "@/hooks/use-interview-kit";
import { TrackKitView, errorMessage } from "./track-kit-view";

interface Props {
  applicationId: number;
  canWrite: boolean;
  /** Which round is in progress. Labelled only past the first, where a
   *  reset of every sheet is otherwise indistinguishable from a round
   *  that never happened. */
  interviewRound?: number;
}

export function InterviewKitSection({ applicationId, canWrite, interviewRound }: Props) {
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

  const first = tracks[0];
  return (
    <TrackKitView
      applicationId={applicationId}
      canWrite={canWrite}
      interviewRound={interviewRound}
      track={tracks.length > 1 ? first.track : null}
      kit={first.kit}
      templateName={first.template_name}
      sheets={sheets}
    />
  );
}
