import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import type { EditableQuestion } from "@/components/interview/question-list-editor";

export type ProbeMode = "score_gaps" | "profile" | "none";

export interface InterviewTemplate {
  id: number;
  name: string;
  description: string | null;
  questions: EditableQuestion[];
  probe_mode: ProbeMode;
  include_job_questions: boolean;
  is_active: boolean;
}

/** What kind of interview a template runs. Derived from its two settings
 *  rather than stored, so a template can never be labelled "HR" while
 *  generating questions from the scorecard. Anything that is neither
 *  preset is "custom" — a deliberate mix, named rather than guessed at. */
export type InterviewKind = "technical" | "hr" | "custom";

interface KindSettings {
  probe_mode: ProbeMode;
  include_job_questions: boolean;
}

const PRESETS: Record<Exclude<InterviewKind, "custom">, KindSettings> = {
  technical: { probe_mode: "score_gaps", include_job_questions: true },
  hr: { probe_mode: "profile", include_job_questions: false },
};

export const KIND_LABEL: Record<InterviewKind, string> = {
  technical: "Technical",
  hr: "HR",
  custom: "Custom",
};

/** What each kind does, in the words a recruiter would use. */
export const KIND_SUMMARY: Record<InterviewKind, string> = {
  technical:
    "Questions generated from the candidate's scorecard gaps, after the job's own questions.",
  hr: "Questions generated from the candidate's career history. The job's own questions are left out.",
  custom: "Set the question sources yourself.",
};

/** Where a mode's questions come from, for a mix the presets don't name. */
const PROBE_SUMMARY: Record<ProbeMode, string> = {
  score_gaps: "Questions generated from the candidate's scorecard gaps.",
  profile: "Questions generated from the candidate's career history.",
  none: "No generated questions — the template's own only.",
};

export function interviewKind(settings: KindSettings): InterviewKind {
  const matches = (preset: KindSettings) =>
    preset.probe_mode === settings.probe_mode
    && preset.include_job_questions === settings.include_job_questions;
  if (matches(PRESETS.technical)) return "technical";
  if (matches(PRESETS.hr)) return "hr";
  return "custom";
}

/** The settings a preset stands for. `custom` keeps whatever is already
 *  set: choosing it changes nothing until the controls are edited.
 *
 *  Always a fresh object: PRESETS is the one definition every label in the
 *  app is matched against, and a caller editing what it got back would
 *  rewrite it for the session. */
export function settingsForKind(kind: InterviewKind, current?: KindSettings): KindSettings {
  if (kind === "custom") {
    return { ...(current ?? { probe_mode: "none", include_job_questions: false }) };
  }
  return { ...PRESETS[kind] };
}

/** What a template does, in the words a recruiter would use. The presets
 *  read as themselves; a mix neither preset names is spelled out from its
 *  two settings, since "custom" on its own describes nothing. */
export function settingsSummary(settings: KindSettings): string {
  const kind = interviewKind(settings);
  if (kind !== "custom") return KIND_SUMMARY[kind];
  return `${PROBE_SUMMARY[settings.probe_mode]} ${
    settings.include_job_questions
      ? "The job's own questions are included."
      : "The job's own questions are left out."
  }`;
}

/** "RH screen · HR" — a template's name with what it runs. Written once:
 *  three pickers and the kit screen all label templates this way, and four
 *  test files read the result. */
export function withKind(name: string, settings: KindSettings): string {
  return `${name} · ${KIND_LABEL[interviewKind(settings)]}`;
}

export function useInterviewTemplates(includeArchived = false, enabled = true) {
  return useQuery({
    queryKey: queryKeys.interviewTemplates(includeArchived),
    queryFn: () =>
      api<InterviewTemplate[]>(`/api/interview-templates?include_archived=${includeArchived}`),
    enabled,
  });
}

/** Create when `id` is undefined, otherwise PATCH. Archiving is a PATCH of
 *  `{ is_active: false }`. Invalidates both archived and active lists. */
export function useSaveInterviewTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id?: number; body: Partial<InterviewTemplate> }) =>
      id === undefined
        ? api<InterviewTemplate>("/api/interview-templates", { method: "POST", json: body })
        : api<InterviewTemplate>(`/api/interview-templates/${id}`, { method: "PATCH", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["interview-templates"] }),
  });
}
