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
  // Kept in the Props shape so the wizard's call-site is unchanged. Unused
  // until the Gmail option is reactivated — see comment in render below.
  hasGoogleOauth?: boolean;
}

export function StepChannel({
  value,
  onChange,
  hasSmtpConfig,
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
          {/*
            Gmail + Google Calendar is intentionally hidden until the backend
            actually wires it up — POST /api/applications/{id}/notify currently
            returns 501 for channel="gmail". Re-enable this option (and remove
            the matching note in the README) once the OAuth + Calendar flow
            lands.
          */}
        </SelectContent>
      </Select>
      <p className="text-sm text-muted-foreground">
        Email is sent from your configured SMTP server with a calendar
        attachment.
      </p>
    </div>
  );
}
