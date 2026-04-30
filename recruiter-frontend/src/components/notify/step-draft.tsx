import { useEffect } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useDraftEmail } from "@/hooks/use-notify";
import type { Slot } from "@/hooks/use-notify";

interface Props {
  applicationId: number;
  slots: Slot[];
  subject: string;
  body: string;
  onChange: (subject: string, body: string) => void;
}

export function StepDraft({
  applicationId,
  slots,
  subject,
  body,
  onChange,
}: Props) {
  const draft = useDraftEmail(applicationId);

  useEffect(() => {
    if (subject === "" && body === "" && slots.length > 0 && !draft.isPending) {
      draft.mutate(slots, {
        onSuccess: (d) => onChange(d.subject, d.body),
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Label>Subject</Label>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() =>
            draft.mutate(slots, {
              onSuccess: (d) => onChange(d.subject, d.body),
            })
          }
          disabled={draft.isPending}
        >
          {draft.isPending ? (
            <Loader2 className="h-4 w-4 mr-1 animate-spin" />
          ) : (
            <Sparkles className="h-4 w-4 mr-1" />
          )}
          {subject || body ? "Re-draft" : "Draft with AI"}
        </Button>
      </div>
      <Input value={subject} onChange={(e) => onChange(e.target.value, body)} />

      <Label>Body</Label>
      <Textarea
        rows={12}
        value={body}
        onChange={(e) => onChange(subject, e.target.value)}
      />
    </div>
  );
}
