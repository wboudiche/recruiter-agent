import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

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

interface KitResponse {
  kit: InterviewKit | null;
  sheets: SheetRead[];
}

export function useInterviewKit(applicationId: number) {
  const qc = useQueryClient();
  const key = queryKeys.interviewKit(applicationId);
  const path = `/api/applications/${applicationId}/interview-kit`;

  const query = useQuery({
    queryKey: key,
    queryFn: () => api<KitResponse>(path),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: key });
    qc.invalidateQueries({ queryKey: queryKeys.interviewers(applicationId) });
  };

  const generate = useMutation({
    mutationFn: () => api(`${path}/generate`, { method: "POST" }),
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
      api<KitResponse>(path, { method: "PATCH", json: { questions } }),
    onSuccess: (data) => {
      qc.setQueryData(key, data);
      invalidate();
    },
  });

  const saveSheet = useMutation({
    mutationFn: (sheet: InterviewSheet) =>
      api<KitResponse>(`${path}/sheet`, { method: "PATCH", json: sheet }),
    onSuccess: (data) => {
      qc.setQueryData(key, data);
      invalidate();
    },
  });

  const submitSheet = useMutation({
    mutationFn: () => api<KitResponse>(`${path}/sheet/submit`, { method: "POST" }),
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
        `${path}/draft-question`,
        { method: "POST", json: { hint } },
      ),
  });

  return {
    draftQuestion,
    kit: query.data?.kit ?? null,
    sheets: query.data?.sheets ?? [],
    isLoading: query.isLoading,
    // A fetch failure (e.g. a 500) must be distinguishable from "no kit
    // exists yet" — collapsing both to `kit: null` makes a real error
    // render as the absent state, offering "Generate" as if nothing were
    // wrong.
    isError: query.isError,
    refetch: query.refetch,
    generate,
    patch,
    saveSheet,
    submitSheet,
  };
}
