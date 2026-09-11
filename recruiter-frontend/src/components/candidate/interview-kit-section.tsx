import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
  const { kit, isLoading, isError, refetch, generate, patch, submit, draftQuestion } =
    useInterviewKit(applicationId);
  const [draft, setDraft] = useState<KitQuestion[]>([]);
  const [hint, setHint] = useState("");

  // The server is the source of truth; local edits are a draft until saved.
  // Deliberately keyed on `generated_at`/`status`, not on `kit.questions`
  // itself: a background refetch must not clobber answers the recruiter has
  // typed but not yet saved.
  //
  // This seeding used to live in a `useEffect`. Effects run after the
  // commit that first shows a loaded `kit`, so there was a render — the one
  // that made `kit.questions` visible — where `draft` was still `[]` from
  // the previous render and hadn't yet been reset. `isDirty` (below) reads
  // `true` in that window purely because hydration hasn't happened, not
  // because of any edit, and a `beforeunload` handler keyed on `isDirty`
  // would attach for it. Normally a cascading re-render clears it again
  // before anything observes it, but that cleanup itself happens in a
  // *later* effect flush, so nothing guarantees it wins a race against
  // whatever runs immediately after the commit (in tests, an assertion
  // right after `waitFor` resolves — see interview-kit-section.test.tsx).
  //
  // Seeding during render instead — React's documented pattern for
  // resetting state when a prop changes — removes the window rather than
  // racing to close it: the mismatched render is discarded and redone with
  // the fresh draft before anything commits, so `isDirty` below can never
  // observe an unseeded draft as dirty.
  const seedKey = kit ? `${kit.generated_at}:${kit.status}` : null;
  const [seededKey, setSeededKey] = useState<string | null>(null);
  if (kit?.questions && seedKey !== seededKey) {
    setSeededKey(seedKey);
    setDraft(kit.questions);
  }

  // Dirty = the draft has diverged from the last-saved questions. Used both
  // for a visible affordance on Save and to warn before an unsaved
  // navigation/refresh wipes typed answers and ratings.
  const isDirty = JSON.stringify(draft) !== JSON.stringify(kit?.questions ?? []);

  useEffect(() => {
    if (!isDirty) return;
    function handler(e: BeforeUnloadEvent) {
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty]);

  if (isLoading) return null;

  if (isError) {
    return (
      <section className="space-y-2">
        <h3 className="text-lg font-semibold">Interview kit</h3>
        <p className="text-xs border border-red-400 bg-red-50 text-red-900 rounded p-2">
          Couldn't load the interview kit.
        </p>
        <Button variant="outline" onClick={() => refetch()}>Retry</Button>
      </section>
    );
  }

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
                // Questions run to 200+ characters; a single-line input
                // clipped them so the interviewer couldn't read what to
                // ask. `field-sizing: content` grows the box to fit (see
                // jobs-new.tsx for browser support); `rows={1}` keeps a
                // short question on one line where it isn't supported.
                <textarea
                  aria-label={`Question ${i + 1}`}
                  rows={1}
                  className="flex-1 resize-none bg-transparent text-sm leading-snug outline-none [field-sizing:content]"
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
          <div className="flex items-center gap-2">
            <Input
              placeholder="about… (optional)"
              aria-label="What the AI-drafted question should be about"
              className="h-9 w-56"
              value={hint}
              onChange={(e) => setHint(e.target.value)}
            />
            <Button
              variant="outline"
              disabled={draftQuestion.isPending}
              onClick={() => {
                // An empty box means "suggest anything missing", which the
                // backend reads as a null hint — not an empty string.
                draftQuestion.mutate(hint.trim() || null, {
                  onSuccess: (res) => {
                    setDraft((qs) => [...qs, {
                      id: newQuestionId(),
                      text: res.question.text,
                      source: "probe",
                      criterion: res.question.criterion,
                      answer: null,
                      rating: null,
                    }]);
                    setHint("");
                  },
                  onError: (err) =>
                    toast.error(errorMessage(err, "Could not draft a question")),
                });
              }}
            >
              {draftQuestion.isPending ? "Drafting…" : "Draft with AI"}
            </Button>
          </div>
          <Button
            variant="outline"
            onClick={saveAnswers}
            data-dirty={isDirty}
            className={isDirty ? "border-amber-400 text-amber-400" : undefined}
          >
            Save answers{isDirty && <span aria-hidden="true">*</span>}
          </Button>
          <Button onClick={onSubmit}>Submit interview</Button>
        </div>
      )}
    </section>
  );
}
