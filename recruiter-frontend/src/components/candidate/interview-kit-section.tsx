import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useInterviewers } from "@/hooks/use-interviewers";
import {
  EMPTY_SHEET, type InterviewSheet, type KitQuestion, type Rating, type VerdictDecision,
  useInterviewKit,
} from "@/hooks/use-interview-kit";
import { FeedbackTable } from "./feedback-table";

const RATINGS: Rating[] = ["strong", "adequate", "weak"];

const VERDICTS: { value: VerdictDecision; label: string }[] = [
  { value: "hire", label: "Hire" },
  { value: "no_hire", label: "No hire" },
  { value: "unsure", label: "Unsure" },
];

interface Props {
  applicationId: number;
  canWrite: boolean;
  /** Which round is in progress. Labelled only past the first, where a
   *  reset of every sheet is otherwise indistinguishable from a round
   *  that never happened. */
  interviewRound?: number;
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

export function InterviewKitSection({ applicationId, canWrite, interviewRound }: Props) {
  const { kit, sheets, isLoading, isError, refetch, generate, patch, saveSheet, submitSheet, draftQuestion } =
    useInterviewKit(applicationId);
  const me = useCurrentUser();
  const { interviewers } = useInterviewers(applicationId);
  const [draft, setDraft] = useState<KitQuestion[]>([]);
  // Explicit edit flag rather than diffing `draft` against `kit.questions`:
  // a background refetch can update `kit.questions` (someone else's edit)
  // without the user having touched anything, and a JSON diff would then
  // read as "changed" for the wrong reason — resending the whole draft as
  // a PATCH would silently overwrite that other edit. Only the user's own
  // edits (below) set this, and only a successful PATCH or a re-seed from
  // the server clears it.
  const [questionsDirty, setQuestionsDirty] = useState(false);
  const [hint, setHint] = useState("");
  const [sheet, setSheet] = useState<InterviewSheet>(EMPTY_SHEET);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const myId = me.data?.id ?? null;
  // Whether the caller may write a sheet is derived, not passed in: it's
  // their own sheet's identity (present + not yet submitted), or — for a
  // writer who has never touched this kit — the fact that no one has
  // created a sheet yet, so the server will create theirs on first save.
  //
  // For a recruiter/admin, `sheets` is every sheet on the kit (not just
  // theirs), so `sheets.length === 0` really does mean "no one has a panel
  // row yet". This mirrors the server: a recruiter/admin with no assignment
  // row on the application gets one created on first save; an unassigned
  // recruiter on an application that already has rows gets a 404.
  const mySheetRead = sheets.find((s) => s.user_id === myId) ?? null;
  const canWriteSheet = mySheetRead ? mySheetRead.submitted_at === null : (canWrite && sheets.length === 0);
  const isSubmitted = mySheetRead?.submitted_at != null;
  // Once any interviewer has submitted, the question list freezes for
  // removal — every sheet keeps scoring against the same set of questions.
  // Question ids are stable, so renaming an existing question's text stays
  // allowed after a freeze; only Remove (and regenerate, not a button here)
  // are refused.
  const frozen = sheets.some((s) => s.submitted_at !== null);
  // A recruiter/admin may always reword a question's text; an interviewer
  // (no `canWrite`) may only edit a question they appended this session
  // (see `canEditThisQuestion` below) — freezing never affects this.
  const canEditQuestions = canWrite;
  const canAppend = canWrite || mySheetRead !== null;

  // "added by" resolves an id to a name for display. `sheets` only covers
  // people who have saved a sheet; `interviewers` covers everyone assigned
  // to the panel (visible to every role), so combine both — a name beats an
  // email, and an id neither list recognizes falls back to a generic label.
  const nameById = new Map<number, string>();
  for (const s of sheets) nameById.set(s.user_id, s.name ?? s.email);
  for (const i of interviewers) if (!nameById.has(i.user_id)) nameById.set(i.user_id, i.name ?? i.email);
  const addedByName = (id: number) => nameById.get(id) ?? "another interviewer";

  // The server is the source of truth; local edits are a draft until saved.
  // Keyed on `generated_at`/`status` plus a stable digest of the questions
  // themselves (id+text), so an *untouched* draft follows the server even
  // when neither `generated_at` nor `status` changes — e.g. a colleague
  // appends a question and a background refetch picks it up. Re-seeding is
  // gated on `!questionsDirty` so a user's own in-progress edits are never
  // clobbered by that same background refetch.
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
  // `generated_at:status` (a regenerate) and the questions digest (an
  // in-place edit, e.g. a colleague appending a question) are tracked
  // separately: a regenerate always re-seeds once the draft is clean (as
  // before), but a digest-only change additionally requires the sheet to be
  // clean too (see R9 below) — a dirty sheet may hold an unsaved answer for
  // a question a refetch just dropped, and re-seeding would wipe that row
  // out from under the answer being typed for it. `seededDigest` also feeds
  // the staleness check in `saveAll` (R2): it's the digest the current
  // draft was seeded from, so a mismatch against the live server digest
  // means the draft was built against a question list that no longer
  // exists server-side.
  const questionsDigest = (qs: KitQuestion[] | undefined) =>
    (qs ?? []).map((q) => `${q.id}:${q.text}`).join("|");
  const serverDigest = kit ? questionsDigest(kit.questions) : null;
  const genKey = kit ? `${kit.generated_at}:${kit.status}` : null;
  const sheetDirty = JSON.stringify(sheet) !== JSON.stringify(mySheetRead?.sheet ?? EMPTY_SHEET);
  const [seededGenKey, setSeededGenKey] = useState<string | null>(null);
  const [seededDigest, setSeededDigest] = useState<string | null>(null);
  if (kit?.questions) {
    const genChanged = genKey !== seededGenKey;
    const digestChanged = serverDigest !== seededDigest;
    const shouldReseed = genChanged ? !questionsDirty : (digestChanged && !questionsDirty && !sheetDirty);
    if (shouldReseed) {
      setSeededGenKey(genKey);
      setSeededDigest(serverDigest);
      setDraft(kit.questions);
      setQuestionsDirty(false);
    }
  }

  // Same seeding pattern for the caller's own sheet, keyed on its identity
  // (whose sheet, and whether it's been submitted) so a background refetch
  // never clobbers answers being typed.
  const sheetKey = mySheetRead ? `${mySheetRead.user_id}:${mySheetRead.submitted_at}` : "none";
  const [seededSheetKey, setSeededSheetKey] = useState<string | null>(null);
  if (sheetKey !== seededSheetKey) {
    setSeededSheetKey(sheetKey);
    setSheet(mySheetRead?.sheet ?? EMPTY_SHEET);
  }

  const setAnswer = (id: string, fields: Partial<{ answer: string | null; rating: Rating | null }>) =>
    setSheet((s) => {
      const current = s.answers[id] ?? { answer: null, rating: null };
      return { ...s, answers: { ...s.answers, [id]: { ...current, ...fields } } };
    });

  // Dirty = the user has edited the question draft, or the sheet draft has
  // diverged from what the server last returned. Used both for a visible
  // affordance on Save and to warn before an unsaved navigation/refresh
  // wipes typed answers. `questionsDirty` (not a diff against
  // `kit.questions`) avoids flagging dirty purely because a background
  // refetch changed the server's list underneath an untouched draft.
  const isDirty = questionsDirty || sheetDirty;

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

  // Only take over the whole section when there is nothing else to show. A
  // failed regeneration KEEPS the questions it already had (see
  // run_generate_kit), and sheets may already hold answers against them —
  // so an error over a populated kit is a banner, not a screen. Retry is
  // recruiter-only, which made the bare screen a dead end for an
  // interviewer: no questions, no sheet, no way out.
  if (kit.status === "error" && kit.questions.length === 0) {
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

  const update = (id: string, patchFields: Partial<KitQuestion>) => {
    setQuestionsDirty(true);
    setDraft((qs) => qs.map((q) => (q.id === id ? { ...q, ...patchFields } : q)));
  };

  const unanswered = draft.filter((q) => !sheet.answers[q.id]?.answer?.trim()).length;
  const serverQuestionIds = new Set((kit.questions ?? []).map((q) => q.id));

  function discardQuestionEdits() {
    if (!kit) return;
    setSeededGenKey(genKey);
    setSeededDigest(serverDigest);
    setDraft(kit.questions);
    setQuestionsDirty(false);
  }

  function saveAll(onDone?: () => void) {
    const afterQuestions = () =>
      canWriteSheet
        ? saveSheet.mutate(sheet, {
            onError: (err) => toast.error(errorMessage(err, "Couldn't save answers")),
            onSuccess: onDone,
          })
        : onDone?.();
    // The draft was built against a question list that no longer matches
    // the server's (a colleague appended/edited/removed a question since
    // this draft was seeded). PATCHing it now would either silently drop
    // their change (recruiter/admin) or 403 forever (a viewer without
    // write access to the question list) — so refuse the questions PATCH
    // and surface it, while still saving the sheet, which is independent.
    if (questionsDirty && serverDigest !== seededDigest) {
      toast.error("Questions changed on the server — discard your question edits to continue");
      afterQuestions();
      return;
    }
    if (questionsDirty && canAppend) {
      patch.mutate(draft, {
        onError: (err) => toast.error(errorMessage(err, "Couldn't save questions")),
        onSuccess: () => {
          setQuestionsDirty(false);
          afterQuestions();
        },
      });
    } else {
      afterQuestions();
    }
  }

  function doSubmit() {
    setConfirmOpen(false);
    saveAll(() =>
      submitSheet.mutate(undefined, {
        onSuccess: () => toast.success("Interview recorded"),
        onError: (err) => toast.error(errorMessage(err, "Answers saved, but submit failed — try again")),
      }));
  }

  function onSubmitClick() {
    if (unanswered > 0) setConfirmOpen(true);
    else doSubmit();
  }

  return (
    <section className="space-y-3">
      <h3 className="text-lg font-semibold">
        Interview kit
        {(interviewRound ?? 1) > 1 && (
          <span className="ml-2 text-xs font-normal uppercase tracking-[0.18em] text-muted-foreground">
            Round {interviewRound}
          </span>
        )}
      </h3>
      {kit.status === "error" && (
        <p className="text-xs border border-yellow-400 bg-yellow-50 text-yellow-900 rounded p-2">
          {kit.error ?? "Generation failed."} The questions below are the ones
          already on the kit.
        </p>
      )}
      <ul className="space-y-3">
        {draft.map((q, i) => {
          const mine = sheet.answers[q.id] ?? { answer: null, rating: null };
          const canEditThisQuestion = canEditQuestions || (canAppend && !serverQuestionIds.has(q.id));
          return (
            <li key={q.id} className="border border-border rounded p-2 space-y-2">
              <div className="flex items-start justify-between gap-2">
                {canEditThisQuestion ? (
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
                {q.added_by != null && (
                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    added by {addedByName(q.added_by)}
                  </span>
                )}
                {canWrite && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-auto px-2 py-1 text-xs"
                    aria-label={`Remove question ${i + 1}`}
                    disabled={frozen}
                    title={frozen ? "Questions are frozen once a sheet is submitted" : undefined}
                    onClick={() => {
                      setQuestionsDirty(true);
                      setDraft((qs) => qs.filter((x) => x.id !== q.id));
                    }}
                  >
                    Remove
                  </Button>
                )}
              </div>
              {(q.answer || q.rating) && (
                <p className="text-xs text-muted-foreground">
                  <span className="uppercase tracking-wide">Recorded before interviewer sheets</span>
                  {q.answer && <> — <span>{q.answer}</span></>}
                  {q.rating && <> (<span>{q.rating}</span>)</>}
                </p>
              )}
              {canWriteSheet ? (
                <>
                  <Textarea
                    placeholder="What they said…"
                    value={mine.answer ?? ""}
                    onChange={(e) => setAnswer(q.id, { answer: e.target.value })}
                  />
                  <div className="flex gap-1">
                    {RATINGS.map((r) => (
                      <Button
                        key={r}
                        type="button"
                        size="sm"
                        variant={mine.rating === r ? "default" : "outline"}
                        className="h-auto px-2 py-1 text-xs capitalize"
                        aria-label={`Rate question ${i + 1} as ${r}`}
                        onClick={() => setAnswer(q.id, { rating: mine.rating === r ? null : r })}
                      >
                        {r}
                      </Button>
                    ))}
                  </div>
                </>
              ) : isSubmitted ? (
                <>
                  {mine.answer && <p className="text-xs">{mine.answer}</p>}
                  {mine.rating && <p className="text-xs text-muted-foreground capitalize">{mine.rating}</p>}
                </>
              ) : null}
            </li>
          );
        })}
      </ul>
      <div className="flex flex-wrap items-center gap-2">
        {canAppend && (
          <Button
            variant="outline"
            onClick={() => {
              setQuestionsDirty(true);
              setDraft((qs) => [...qs, {
                id: newQuestionId(), text: "", source: "probe",
                criterion: null, answer: null, rating: null, added_by: myId,
              }]);
            }}
          >
            Add question
          </Button>
        )}
        {canAppend && (
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
                    setQuestionsDirty(true);
                    setDraft((qs) => [...qs, {
                      id: newQuestionId(),
                      text: res.question.text,
                      source: "probe",
                      criterion: res.question.criterion,
                      answer: null,
                      rating: null,
                      added_by: myId,
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
        )}
        {(canWriteSheet || canAppend) && (
          <>
            <Button
              variant="outline"
              onClick={() => saveAll()}
              data-dirty={isDirty}
              className={isDirty ? "border-amber-400 text-amber-400" : undefined}
              disabled={saveSheet.isPending || patch.isPending || submitSheet.isPending}
            >
              {canWriteSheet ? "Save answers" : "Save questions"}{isDirty && <span aria-hidden="true">*</span>}
            </Button>
            {questionsDirty && (
              <Button
                variant="ghost"
                onClick={discardQuestionEdits}
                disabled={saveSheet.isPending || patch.isPending || submitSheet.isPending}
              >
                Discard question edits
              </Button>
            )}
            {canWriteSheet && (
              <Button
                onClick={onSubmitClick}
                disabled={saveSheet.isPending || patch.isPending || submitSheet.isPending}
              >
                Submit interview
              </Button>
            )}
          </>
        )}
      </div>
      {canWriteSheet && (
        <div className="space-y-2 rounded border border-border p-2">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Verdict</p>
          <div className="flex gap-1">
            {VERDICTS.map((v) => (
              <Button
                key={v.value}
                type="button"
                size="sm"
                variant={sheet.verdict.decision === v.value ? "default" : "outline"}
                className="h-auto px-2 py-1 text-xs"
                onClick={() => setSheet((s) => ({
                  ...s,
                  verdict: { ...s.verdict, decision: s.verdict.decision === v.value ? null : v.value },
                }))}
              >
                {v.label}
              </Button>
            ))}
          </div>
          <Textarea
            aria-label="Verdict note"
            placeholder="One line on why…"
            value={sheet.verdict.note ?? ""}
            onChange={(e) => setSheet((s) => ({ ...s, verdict: { ...s.verdict, note: e.target.value || null } }))}
          />
        </div>
      )}
      {canWrite && sheets.length > 1 && <FeedbackTable questions={draft} sheets={sheets} />}
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Submit with unanswered questions?</DialogTitle>
          </DialogHeader>
          <DialogDescription>
            {unanswered} question(s) have no answer. Submit anyway?
          </DialogDescription>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>Keep editing</Button>
            <Button
              onClick={doSubmit}
              disabled={saveSheet.isPending || patch.isPending || submitSheet.isPending}
            >
              Submit anyway
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
