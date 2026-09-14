import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { KitQuestion, Rating, SheetRead, VerdictDecision } from "@/hooks/use-interview-kit";

const RATING_CLASS: Record<Rating, string> = {
  strong: "border-emerald-500/60 text-emerald-300",
  adequate: "border-amber-500/60 text-amber-300",
  weak: "border-red-500/60 text-red-300",
};

const VERDICT_LABEL: Record<VerdictDecision, string> = {
  hire: "Hire", no_hire: "No hire", unsure: "Unsure",
};

interface Props {
  questions: KitQuestion[];
  sheets: SheetRead[];
}

export function FeedbackTable({ questions, sheets }: Props) {
  const [showUnrated, setShowUnrated] = useState(false);
  const rated = (q: KitQuestion) => sheets.some((s) => s.sheet.answers[q.id]?.rating);
  const unratedCount = questions.filter((q) => !rated(q)).length;
  const rows = showUnrated ? questions : questions.filter(rated);

  return (
    <section className="space-y-2">
      <h4 className="text-sm font-semibold">Feedback</h4>
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
