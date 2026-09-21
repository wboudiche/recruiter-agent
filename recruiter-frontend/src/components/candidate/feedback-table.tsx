import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { KitQuestion, Rating, SheetRead, VerdictDecision } from "@/hooks/use-interview-kit";

const RATING_CLASS: Record<Rating, string> = {
  strong: "border-success-line text-success",
  adequate: "border-warning-line text-warning",
  weak: "border-danger-line text-danger",
};

const VERDICT_LABEL: Record<VerdictDecision, string> = {
  hire: "Hire", no_hire: "No hire", unsure: "Unsure",
};

interface Props {
  questions: KitQuestion[];
  sheets: SheetRead[];
  /** The round in progress. Sheets from earlier rounds are filtered out:
   *  the same interviewer holds one per round after a reopen, which would
   *  otherwise collide React keys on user_id and make the verdict tally
   *  count the whole history instead of this round. */
  interviewRound?: number;
}

/**
 * "2 hire · 1 unsure · 1 outstanding" — the shape of the panel's opinion in
 * one line. Only SUBMITTED sheets are counted: a verdict still in draft is
 * not a decision, and folding it in would report a split panel as settled.
 * Everything else — unsubmitted, or submitted with no decision recorded —
 * is named as outstanding rather than quietly dropped, so the counts always
 * add up to the panel.
 */
function verdictSummary(sheets: SheetRead[]): string | null {
  const submitted = sheets.filter((s) => s.submitted_at);
  if (submitted.length === 0) return null;

  const counts: Record<VerdictDecision, number> = { hire: 0, unsure: 0, no_hire: 0 };
  for (const s of submitted) {
    if (s.sheet.verdict.decision) counts[s.sheet.verdict.decision] += 1;
  }
  const outstanding = sheets.length - (counts.hire + counts.unsure + counts.no_hire);

  const parts = (["hire", "unsure", "no_hire"] as const)
    .filter((k) => counts[k] > 0)
    .map((k) => `${counts[k]} ${VERDICT_LABEL[k].toLowerCase()}`);
  if (outstanding > 0) parts.push(`${outstanding} outstanding`);
  return parts.join(" · ");
}

export function FeedbackTable({ questions, sheets, interviewRound }: Props) {
  const [showUnrated, setShowUnrated] = useState(false);
  const liveRound = interviewRound ?? 1;
  sheets = sheets.filter((s) => (s.round ?? 1) === liveRound);
  const rated = (q: KitQuestion) => sheets.some((s) => s.sheet.answers[q.id]?.rating);
  const unratedCount = questions.filter((q) => !rated(q)).length;
  const rows = showUnrated ? questions : questions.filter(rated);

  const summary = verdictSummary(sheets);

  return (
    <section className="space-y-2">
      <h4 className="text-sm font-semibold">Feedback</h4>
      {summary && (
        <p aria-label="Verdict summary" className="text-xs text-muted-foreground">
          {summary}
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr>
              <th scope="col" className="text-left font-normal text-muted-foreground">Question</th>
              {sheets.map((s) => (
                <th key={s.user_id} scope="col" className="text-left font-normal">
                  {s.name ?? s.email}{s.submitted_at && <span aria-label="submitted"> ✓</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr aria-label="Verdict">
              <th scope="row" className="text-left font-medium">Verdict</th>
              {sheets.map((s) => (
                <td key={s.user_id}>
                  {s.sheet.verdict.decision ? VERDICT_LABEL[s.sheet.verdict.decision] : "—"}
                  {s.sheet.verdict.note && (
                    <span className="block text-xs text-muted-foreground">{s.sheet.verdict.note}</span>
                  )}
                </td>
              ))}
            </tr>
            {rows.map((q) => (
              <tr key={q.id} aria-label={q.text}>
                <th scope="row" className="text-left font-normal">{q.text}</th>
                {sheets.map((s) => {
                  const a = s.sheet.answers[q.id];
                  return (
                    <td key={s.user_id} className="align-top">
                      {a?.rating ? (
                        <span className={`rounded border px-1.5 py-0.5 text-xs capitalize ${RATING_CLASS[a.rating]}`}>
                          {a.rating}
                        </span>
                      ) : "—"}
                      {a?.answer && (
                        <details className="text-xs text-muted-foreground">
                          <summary>answer</summary>{a.answer}
                        </details>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {unratedCount > 0 && (
        <Button variant="ghost" size="sm" onClick={() => setShowUnrated((v) => !v)}>
          {showUnrated ? `Hide ${unratedCount} unrated` : `Show ${unratedCount} unrated`}
        </Button>
      )}
    </section>
  );
}
