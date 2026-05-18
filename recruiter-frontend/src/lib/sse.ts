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

type ServerEvent = StageEvent | ServerErrorEvent;

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

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

    source.addEventListener("stage", handle);
    source.addEventListener("error", handle);
    source.addEventListener("message", handle);

    return () => source.close();
  }, [path, queryClient]);
}
