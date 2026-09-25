import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import type { ProbeMode } from "./use-interview-templates";

export type Rating = "strong" | "adequate" | "weak";

export type VerdictDecision = "hire" | "no_hire" | "unsure";

export interface SheetAnswer {
  answer: string | null;
  rating: Rating | null;
}

export interface InterviewSheet {
  answers: Record<string, SheetAnswer>;
  verdict: { decision: VerdictDecision | null; note: string | null };
}

export interface SheetRead {
  user_id: number;
  name: string | null;
  email: string;
  sheet: InterviewSheet;
  submitted_at: string | null;
  /** Which round this sheet belongs to. A recruiter is shown every round's
   *  sheets, so user_id alone does not identify one. Optional for safety
   *  against an older server; treat a missing value as round 1. */
  round?: number;
  /** Which track of that round (phase 3). Optional for safety against an
   *  older server; treat a missing value as "default". */
  track?: string;
}

// Frozen: this object is a shared default handed out to every caller with
// no sheet of their own yet. Every update must build a new object (see
// interview-kit-section.tsx's setAnswer/setSheet) — mutating this one would
// corrupt it for every other consumer. Object.freeze makes an accidental
// mutation throw instead of silently leaking across components.
export const EMPTY_SHEET: InterviewSheet = Object.freeze({
  answers: {},
  verdict: { decision: null, note: null },
});

export interface KitQuestion {
  id: string;
  text: string;
  source: "baseline" | "probe";
  criterion?: string | null;
  /** Legacy — answers now live on each interviewer's sheet. Read-only. */
  answer: string | null;
  rating: Rating | null;
  added_by?: number | null;
}

export interface InterviewKit {
  status: "generating" | "ready" | "error";
  error?: string | null;
  generated_at?: string | null;
  submitted_at?: string | null;
  closed_at?: string | null;
  questions: KitQuestion[];
}

export interface TrackRead {
  track: string;
  template_id: number | null;
  template_name: string | null;
  /** What the kit was built to do, from its own snapshot — null when it has
   *  no template. Lets the screen name each track's kind without reading
   *  the templates list, which an interviewer cannot. */
  probe_mode?: ProbeMode | null;
  include_job_questions?: boolean | null;
  kit: InterviewKit;
}

interface KitResponse {
  kit: InterviewKit | null;
  sheets: SheetRead[];
  template_name?: string | null;
  /** Every track of the live round the caller may see (phase 3). */
  tracks?: TrackRead[];
}

/** The live round's tracks. A response without `tracks` (an older server,
 *  or a test fixture) is read as the one track its `kit` describes. */
export function tracksOf(data: KitResponse | undefined): TrackRead[] {
  if (!data) return [];
  if (data.tracks) return data.tracks;
  return data.kit
    ? [{ track: "default", template_id: null, template_name: data.template_name ?? null,
         kit: data.kit }]
    : [];
}

/** `?track=` for a named track; a one-track round sends none. */
function withTrack(url: string, track: string | null): string {
  return track === null ? url : `${url}?track=${encodeURIComponent(track)}`;
}

/** The mutations for one track's kit. `track` null means "the round's only
 *  track": requests carry no `?track=`, exactly as before tracks existed. */
export function useTrackKitActions(applicationId: number, track: string | null) {
  const qc = useQueryClient();
  const key = queryKeys.interviewKit(applicationId);
  const path = `/api/applications/${applicationId}/interview-kit`;

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: key });
    qc.invalidateQueries({ queryKey: queryKeys.interviewers(applicationId) });
  };

  const generate = useMutation({
    mutationFn: () => api(withTrack(`${path}/generate`, track), { method: "POST" }),
    onSuccess: invalidate,
  });

  // Both PATCH endpoints return the full `{kit, sheets}` shape — the same
  // shape the GET query caches — so the response can be written straight
  // into the cache before invalidating. Without this, the cache stays at
  // its pre-save value until the invalidated refetch lands, and a
  // render-phase seed (see interview-kit-section.tsx) reading the stale
  // cache in that window can re-seed the draft from data that predates the
  // save that just succeeded.
  const patch = useMutation({
    mutationFn: (questions: KitQuestion[]) =>
      api<KitResponse>(withTrack(path, track), { method: "PATCH", json: { questions } }),
    onSuccess: (data) => {
      qc.setQueryData(key, data);
      invalidate();
    },
  });

  const saveSheet = useMutation({
    mutationFn: (sheet: InterviewSheet) =>
      api<KitResponse>(withTrack(`${path}/sheet`, track), { method: "PATCH", json: sheet }),
    onSuccess: (data) => {
      qc.setQueryData(key, data);
      invalidate();
    },
  });

  const submitSheet = useMutation({
    mutationFn: () => api<KitResponse>(withTrack(`${path}/sheet/submit`, track), { method: "POST" }),
    onSuccess: () => {
      invalidate();
      // The stage may have changed, so the kanban and the detail header are stale too.
      qc.invalidateQueries({ queryKey: queryKeys.application(applicationId) });
      qc.invalidateQueries({ queryKey: ["jobs"], exact: false });
    },
  });

  // Deliberately no invalidation on success: a draft is handed back for the
  // recruiter to read and reword, and nothing is stored server-side, so there
  // is nothing to refetch.
  const draftQuestion = useMutation({
    mutationFn: (hint: string | null) =>
      api<{ question: { text: string; criterion: string | null } }>(
        withTrack(`${path}/draft-question`, track),
        { method: "POST", json: { hint } },
      ),
  });

  return { generate, patch, saveSheet, submitSheet, draftQuestion };
}

/** Whether a sheet holds anything a recruiter would not want discarded —
 *  mirrors the server's sheet_has_content. */
export function sheetHasContent(sheet: InterviewSheet): boolean {
  return Object.values(sheet.answers).some((a) => a?.answer || a?.rating)
    || !!(sheet.verdict.decision || sheet.verdict.note);
}

/** Adding and removing a track of the live round. Both return the full kit
 *  read, cached as-is. */
export function useTrackMutations(applicationId: number) {
  const qc = useQueryClient();
  const key = queryKeys.interviewKit(applicationId);
  const path = `/api/applications/${applicationId}/interview-tracks`;
  const settle = (data: KitResponse) => {
    qc.setQueryData(key, data);
    qc.invalidateQueries({ queryKey: key });
    qc.invalidateQueries({ queryKey: queryKeys.interviewers(applicationId) });
    // Removing the last unfinished track can close the round.
    qc.invalidateQueries({ queryKey: queryKeys.application(applicationId) });
    // A closed round can also change the board (see submitSheet above).
    qc.invalidateQueries({ queryKey: ["jobs"], exact: false });
  };
  const addTrack = useMutation({
    mutationFn: (templateId: number | null) =>
      api<KitResponse>(path, { method: "POST", json: { template_id: templateId } }),
    onSuccess: settle,
  });
  const removeTrack = useMutation({
    mutationFn: (track: string) =>
      api<KitResponse>(`${path}/${encodeURIComponent(track)}`, { method: "DELETE" }),
    onSuccess: settle,
  });
  return { addTrack, removeTrack };
}

export function useInterviewKit(applicationId: number) {
  const query = useQuery({
    queryKey: queryKeys.interviewKit(applicationId),
    queryFn: () => api<KitResponse>(`/api/applications/${applicationId}/interview-kit`),
  });
  const actions = useTrackKitActions(applicationId, null);

  return {
    ...actions,
    kit: query.data?.kit ?? null,
    sheets: query.data?.sheets ?? [],
    templateName: query.data?.template_name ?? null,
    tracks: tracksOf(query.data),
    isLoading: query.isLoading,
    // A fetch failure (e.g. a 500) must be distinguishable from "no kit
    // exists yet" — collapsing both to `kit: null` makes a real error
    // render as the absent state, offering "Generate" as if nothing were
    // wrong.
    isError: query.isError,
    refetch: query.refetch,
  };
}
