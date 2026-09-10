import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  type KitQuestion, type Rating, useInterviewKit,
} from "@/hooks/use-interview-kit";

const RATINGS: Rating[] = ["strong", "adequate", "weak"];

interface Props {
  applicationId: number;
  canWrite: boolean;
}

export function InterviewKitSection({ applicationId, canWrite }: Props) {
  const { kit, isLoading, generate, patch, submit } = useInterviewKit(applicationId);
  const [draft, setDraft] = useState<KitQuestion[]>([]);

  // The server is the source of truth; local edits are a draft until saved.
  useEffect(() => {
    if (kit?.questions) setDraft(kit.questions);
  }, [kit?.generated_at, kit?.status]);

  if (isLoading) return null;

  if (!kit) {
    return (
      <section className="space-y-2">
        <h3 className="text-lg font-semibold">Interview kit</h3>
        {canWrite && (
          <Button onClick={() => generate.mutate()} disabled={generate.isPending}>
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
          <Button variant="outline" onClick={() => generate.mutate()}>Retry</Button>
        )}
      </section>
    );
  }

  const update = (id: string, patchFields: Partial<KitQuestion>) =>
    setDraft((qs) => qs.map((q) => (q.id === id ? { ...q, ...patchFields } : q)));

  const unanswered = draft.filter((q) => !q.answer?.trim()).length;

  function onSubmit() {
    if (unanswered > 0 &&
        !window.confirm(`${unanswered} question(s) have no answer. Submit anyway?`)) {
      return;
    }
    patch.mutate(draft, {
      onSuccess: () => submit.mutate(undefined, {
        onSuccess: () => toast.success("Interview recorded"),
      }),
    });
  }

  return (
    <section className="space-y-3">
      <h3 className="text-lg font-semibold">Interview kit</h3>
      <ul className="space-y-3">
        {draft.map((q) => (
          <li key={q.id} className="border border-border rounded p-2 space-y-2">
            <div className="flex items-start justify-between gap-2">
              {canWrite ? (
                <input
                  aria-label={`Question: ${q.text}`}
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
                  aria-label={`Remove question: ${q.text}`}
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
                id: `m-${Date.now()}`, text: "", source: "probe",
                criterion: null, answer: null, rating: null,
              }])}
          >
            Add question
          </Button>
          <Button variant="outline" onClick={() => patch.mutate(draft)}>Save answers</Button>
          <Button onClick={onSubmit}>Submit interview</Button>
        </div>
      )}
    </section>
  );
}
