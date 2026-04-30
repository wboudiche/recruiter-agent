import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import type { Slot } from "@/hooks/use-notify";

interface Props {
  channel: "smtp" | "gmail";
  candidateEmail: string;
  subject: string;
  body: string;
  slots: Slot[];
}

function formatSlot(slot: Slot): string {
  const opts: Intl.DateTimeFormatOptions = {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  };
  const start = new Date(slot.start).toLocaleString(undefined, opts);
  const end = new Date(slot.end).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
  return `${start} – ${end}`;
}

export function StepConfirm({
  channel,
  candidateEmail,
  subject,
  body,
  slots,
}: Props) {
  return (
    <div className="space-y-4">
      <Card className="p-4 space-y-2 text-sm">
        <div>
          <Label className="text-xs text-muted-foreground">Channel</Label>
          <p className="font-medium">
            {channel === "smtp" ? "SMTP + ICS" : "Gmail + Google Calendar"}
          </p>
        </div>
        <div>
          <Label className="text-xs text-muted-foreground">Recipient</Label>
          <p>{candidateEmail}</p>
        </div>
        <div>
          <Label className="text-xs text-muted-foreground">Subject</Label>
          <p className="font-medium">{subject}</p>
        </div>
        <div>
          <Label className="text-xs text-muted-foreground">Slots</Label>
          <ul className="list-disc list-inside">
            {slots.map((slot, i) => (
              <li key={i}>{formatSlot(slot)}</li>
            ))}
          </ul>
        </div>
      </Card>
      <div>
        <Label className="text-xs text-muted-foreground">Body preview</Label>
        <pre className="text-sm whitespace-pre-wrap rounded border p-3 bg-muted/30">
          {body}
        </pre>
      </div>
    </div>
  );
}
