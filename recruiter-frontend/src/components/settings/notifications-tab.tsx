import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSettings, useUpdateSettings } from "@/hooks/use-settings";

export function NotificationsTab() {
  const settings = useSettings();
  const update = useUpdateSettings();
  const [host, setHost] = useState("");
  const [port, setPort] = useState("587");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [fromEmail, setFromEmail] = useState("");
  const [useStartTls, setUseStartTls] = useState(true);

  if (settings.isLoading) return <p>Loading…</p>;
  if (!settings.data) return <p>No settings.</p>;

  function save() {
    update.mutate(
      {
        smtp_config: {
          host,
          port: Number(port),
          user,
          password,
          from_email: fromEmail,
          use_starttls: useStartTls,
        },
      },
      { onSuccess: () => setPassword("") },
    );
  }

  const canSave = host && port && fromEmail;

  return (
    <div className="space-y-6 max-w-lg">
      <section className="space-y-3">
        <h3 className="font-medium">SMTP + ICS</h3>
        {settings.data.has_smtp_config && (
          <p className="text-sm text-muted-foreground">
            SMTP config is set. Submit again to overwrite.
          </p>
        )}
        <div className="space-y-2">
          <Label>SMTP host</Label>
          <Input
            placeholder="smtp.example.com"
            value={host}
            onChange={(e) => setHost(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label>Port</Label>
          <Input
            type="number"
            value={port}
            onChange={(e) => setPort(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label>User</Label>
          <Input value={user} onChange={(e) => setUser(e.target.value)} />
        </div>
        <div className="space-y-2">
          <Label>Password</Label>
          <Input
            type="password"
            placeholder={settings.data.has_smtp_config ? "•••••• (set)" : ""}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label>From email</Label>
          <Input
            type="email"
            placeholder="me@example.com"
            value={fromEmail}
            onChange={(e) => setFromEmail(e.target.value)}
          />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={useStartTls}
            onChange={(e) => setUseStartTls(e.target.checked)}
          />
          Use STARTTLS (uncheck for local dev SMTP servers like MailHog)
        </label>
        <Button onClick={save} disabled={update.isPending || !canSave}>
          {update.isPending ? "Saving…" : "Save SMTP config"}
        </Button>
      </section>

      <section className="space-y-3 border-t pt-6">
        <h3 className="font-medium">Gmail + Google Calendar</h3>
        <p className="text-sm text-muted-foreground">
          {settings.data.has_google_oauth_tokens
            ? "Connected to Google."
            : "Gmail + Google Calendar OAuth setup ships in Plan C tasks 13–22 (deferred)."}
        </p>
      </section>
    </div>
  );
}
