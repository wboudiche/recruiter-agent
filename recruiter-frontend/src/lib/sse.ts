import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "./query-keys";

interface StageEvent {
  type: "stage";
  application_id: number;
  stage: string;
  score?: number;
}

interface ServerErrorEvent {
  type: "error";
  application_id: number;
  phase: string;
  error: string;
}

interface InterviewKitEvent {
  type: "interview_kit";
  application_id: number;
  // Absent on events published before the backend started sending them —
  // handle both as "unknown", which we treat conservatively (see below).
  job_id?: number;
  status: "generating" | "ready" | "error";
  stage_changed?: boolean;
}

type ServerEvent = StageEvent | ServerErrorEvent | InterviewKitEvent;

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export function handleServerEvent(
  payload: ServerEvent,
  queryClient: ReturnType<typeof useQueryClient>,
) {
  if (payload.type === "interview_kit") {
    queryClient.invalidateQueries({
      queryKey: queryKeys.interviewKit(payload.application_id),
    });
    queryClient.invalidateQueries({
      queryKey: queryKeys.interviewers(payload.application_id),
    });
    // A sheet submit can move the stage.
    queryClient.invalidateQueries({ queryKey: queryKeys.application(payload.application_id) });
    // When we know which job's board this application lives on, refetch
    // just that job's application list instead of every mounted kanban
    // board. Only fall back to the broad ["jobs"] prefix when the stage
    // actually changed (the card may need to move columns) or when the
    // event predates `job_id`/`stage_changed` (old events — we can't tell
    // whether the stage moved, so refetch everything to be safe).
    if (typeof payload.job_id === "number") {
      queryClient.invalidateQueries({ queryKey: queryKeys.jobApplications(payload.job_id) });
    }
    if (payload.stage_changed === true || payload.job_id === undefined) {
      queryClient.invalidateQueries({ queryKey: ["jobs"], exact: false });
    }
  } else {
    queryClient.invalidateQueries({
      queryKey: queryKeys.application(payload.application_id),
    });
    // Best-effort: refetch any per-job applications list currently mounted.
    queryClient.invalidateQueries({ queryKey: ["jobs"], exact: false });
    // A stage change after extraction means candidate fields (full_name,
    // skills, experience, education, summary) just got populated by the
    // background pipeline. The event doesn't carry the candidate_id, so
    // we invalidate the whole candidate cache — it's small (one row per
    // visible card) and avoids a stale application-detail page.
    queryClient.invalidateQueries({ queryKey: ["candidates"], exact: false });
  }
}

export function useSSE(path: string = "/api/events") {
  const queryClient = useQueryClient();

  useEffect(() => {
    const url = `${BASE_URL}${path}`;
    const source = new EventSource(url);

    function handle(event: MessageEvent) {
      let payload: ServerEvent;
      try {
        payload = JSON.parse(event.data) as ServerEvent;
      } catch {
        return;
      }
      handleServerEvent(payload, queryClient);
    }

    source.addEventListener("stage", handle);
    source.addEventListener("error", handle);
    source.addEventListener("message", handle);
    // The backend names the SSE event after its type (see events.py), so
    // interview_kit progress arrives as `event: interview_kit` — a browser
    // EventSource never routes a named event to a "message" listener, so
    // this needs its own registration or the kit panel spins forever.
    source.addEventListener("interview_kit", handle);

    return () => source.close();
  }, [path, queryClient]);
}
