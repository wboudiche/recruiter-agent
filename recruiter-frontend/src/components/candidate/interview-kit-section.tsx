import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import {
  type KitQuestion, type Rating, useInterviewKit,
} from "@/hooks/use-interview-kit";

const RATINGS: Rating[] = ["strong", "adequate", "weak"];

interface Props {
  applicationId: number;
  canWrite: boolean;
}

// Ids minted client-side for newly-added questions. `Date.now()` alone can
// collide when two rows are added within the same millisecond, and since
// `update`/remove match on id, that would make edits to one row bleed into
// the other. A monotonic counter alongside the timestamp (or a real UUID,
// where available) keeps every minted id unique.
let localIdCounter = 0;
function newQuestionId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  localIdCounter += 1;
  return `m-${Date.now()}-${localIdCounter}`;
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.detail : fallback;
}

export function InterviewKitSection({ applicationId, canWrite }: Props) {
  const { kit, isLoading, generate, patch, submit } = useInterviewKit(applicationId);
  const [draft, setDraft] = useState<KitQuestion[]>([]);

  // The server is the source of truth; local edits are a draft until saved.
  // Deliberately NOT keyed on `kit.questions` itself: a background refetch
  // must not clobber answers the recruiter has typed but not yet saved.
  useEffect(() => {
    if (kit?.questions) setDraft(kit.questions);
  }, [kit?.generated_at, kit?.status]);

  if (isLoading) return null;

  if (!kit) {
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

  if (kit.status === "generating") {
    return (
      <section className="space-y-2">
        <h3 className="text-lg font-semibold">Interview kit</h3>
        <p className="text-xs text-muted-foreground animate-pulse">Generating questions…</p>
      </section>
    );
  }

  if (kit.status === "error") {
    return (
      <section className="space-y-2">
        <h3 className="text-lg font-semibold">Interview kit</h3>
        <p className="text-xs border border-yellow-400 bg-yellow-50 text-yellow-900 rounded p-2">
          {kit.error ?? "Generation failed."}
        </p>
        {canWrite && (
          <Button
            variant="outline"
            onClick={() =>
              generate.mutate(undefined, {
                onError: (err) =>
                  toast.error(errorMessage(err, "Couldn't start generation")),
              })}
          >
            Retry
          </Button>
        )}
      </section>
    );
  }

  const update = (id: string, patchFields: Partial<KitQuestion>) =>
    setDraft((qs) => qs.map((q) => (q.id === id ? { ...q, ...patchFields } : q)));

  const unanswered = draft.filter((q) => !q.answer?.trim()).length;

  function saveAnswers() {
    patch.mutate(draft, {
      onError: (err) => toast.error(errorMessage(err, "Couldn't save answers")),
    });
  }

  function onSubmit() {
    if (unanswered > 0 &&
        !window.confirm(`${unanswered} question(s) have no answer. Submit anyway?`)) {
      return;
    }
    patch.mutate(draft, {
      onError: (err) => toast.error(errorMessage(err, "Couldn't save answers")),
      onSuccess: () => submit.mutate(undefined, {
        onSuccess: () => toast.success("Interview recorded"),
        onError: (err) =>
          toast.error(errorMessage(err, "Answers saved, but submit failed — try again")),
      }),
    });
  }

  return (
    <section className="space-y-3">
      <h3 className="text-lg font-semibold">Interview kit</h3>
      <ul className="space-y-3">
        {draft.map((q, i) => (
          <li key={q.id} className="border border-border rounded p-2 space-y-2">
            <div className="flex items-start justify-between gap-2">
              {canWrite ? (
                <input
                  aria-label={`Question ${i + 1}`}
                  className="flex-1 bg-transparent text-sm outline-none"
                  value={q.text}
                  onChange={(e) => update(q.id, { text: e.target.value })}
                />
              ) : (
                <p className="flex-1 text-sm">{q.text}</p>
              )}
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                {q.source === "baseline" ? "Role" : "For this candidate"}
              </span>
              {canWrite && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-auto px-2 py-1 text-xs"
                  aria-label={`Remove question ${i + 1}`}
                  onClick={() => setDraft((qs) => qs.filter((x) => x.id !== q.id))}
                >
                  Remove
                </Button>
              )}
            </div>
            {canWrite ? (
              <Textarea
                placeholder="What they said…"
                value={q.answer ?? ""}
                onChange={(e) => update(q.id, { answer: e.target.value })}
              />
            ) : (
              q.answer && <p className="text-xs text-muted-foreground">{q.answer}</p>
            )}
            {canWrite && (
              <div className="flex gap-1">
                {RATINGS.map((r) => (
                  <Button
                    key={r}
                    type="button"
                    size="sm"
                    variant={q.rating === r ? "default" : "outline"}
                    className="h-auto px-2 py-1 text-xs capitalize"
                    aria-label={`Rate question ${i + 1} as ${r}`}
                    onClick={() => update(q.id, { rating: q.rating === r ? null : r })}
                  >
                    {r}
                  </Button>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
      {canWrite && (
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() =>
              setDraft((qs) => [...qs, {
                id: newQuestionId(), text: "", source: "probe",
                criterion: null, answer: null, rating: null,
              }])}
          >
            Add question
          </Button>
          <Button variant="outline" onClick={saveAnswers}>Save answers</Button>
          <Button onClick={onSubmit}>Submit interview</Button>
        </div>
      )}
    </section>
  );
}
