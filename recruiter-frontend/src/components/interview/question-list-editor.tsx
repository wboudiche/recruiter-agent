import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export interface EditableQuestion {
  id: string;
  text: string;
  criterion?: string | null;
}

// A bare `Date.now()` collides when two rows are added within the same
// millisecond, and the rows then track each other's edits (they share an
// id). Prefer the collision-proof `crypto.randomUUID()`; fall back to a
// monotonic counter appended to the timestamp where it isn't available.
let questionIdCounter = 0;

export function newQuestionId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  questionIdCounter += 1;
  return `b-${Date.now()}-${questionIdCounter}`;
}

interface Props {
  rows: EditableQuestion[];
  onChange: (rows: EditableQuestion[]) => void;
  canWrite: boolean;
  /** Label for each row, e.g. "Baseline question" → "Baseline question 1". */
  labelPrefix: string;
  /** Prefix of each input's DOM id, e.g. "baseline" → `baseline-<row id>`. */
  idPrefix: string;
  emptyMessage: React.ReactNode;
}

export function QuestionListEditor({
  rows, onChange, canWrite, labelPrefix, idPrefix, emptyMessage,
}: Props) {
  const update = (i: number, text: string) =>
    onChange(rows.map((r, idx) => (idx === i ? { ...r, text } : r)));
  const remove = (i: number) => onChange(rows.filter((_, idx) => idx !== i));
  const add = () => onChange([...rows, { id: newQuestionId(), text: "" }]);

  return (
    <>
      {canWrite && (
        <div className="flex items-center gap-2 py-3 border-b">
          <Button type="button" variant="outline" size="sm" onClick={add}>
            <Plus className="h-4 w-4 mr-1" />
            Add question
          </Button>
        </div>
      )}
      <div className="flex-1 overflow-y-auto space-y-4 py-4">
        {rows.length === 0 && (
          <p className="text-sm text-muted-foreground italic">{emptyMessage}</p>
        )}
        {rows.map((row, i) => (
          <div key={row.id} className="flex gap-2 items-end">
            <div className="flex-1 space-y-1">
              <Label htmlFor={`${idPrefix}-${row.id}`}>{labelPrefix} {i + 1}</Label>
              <Input
                id={`${idPrefix}-${row.id}`}
                value={row.text}
                onChange={(e) => update(i, e.target.value)}
                readOnly={!canWrite}
              />
            </div>
            {canWrite && (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                // Deliberately doesn't repeat the row label: any lookup
                // matching on it would otherwise resolve both the input and
                // this button and pick whichever sorts last.
                aria-label={`Remove question ${i + 1}`}
                onClick={() => remove(i)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
