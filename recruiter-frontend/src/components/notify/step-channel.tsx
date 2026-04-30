import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface Props {
  value: "smtp" | "gmail";
  onChange: (channel: "smtp" | "gmail") => void;
  hasSmtpConfig: boolean;
  hasGoogleOauth: boolean;
}

export function StepChannel({
  value,
  onChange,
  hasSmtpConfig,
  hasGoogleOauth,
}: Props) {
  return (
    <div className="space-y-4">
      <Label>Channel</Label>
      <Select
        value={value}
        onValueChange={(v) => onChange(v as "smtp" | "gmail")}
      >
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="smtp" disabled={!hasSmtpConfig}>
            SMTP + ICS attachment{" "}
            {!hasSmtpConfig && "(configure in Settings)"}
          </SelectItem>
          <SelectItem value="gmail" disabled={!hasGoogleOauth}>
            Gmail + Google Calendar{" "}
            {!hasGoogleOauth && "(connect in Settings)"}
          </SelectItem>
        </SelectContent>
      </Select>
      <p className="text-sm text-muted-foreground">
        {value === "smtp"
          ? "Email is sent from your configured SMTP server with a calendar attachment."
          : "Email is sent from your Gmail account; a Google Calendar event with the candidate as attendee is created."}
      </p>
    </div>
  );
}
