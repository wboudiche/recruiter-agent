import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSettings, useUpdateSettings } from "@/hooks/use-settings";

export function ProfileTab() {
  const settings = useSettings();
  const update = useUpdateSettings();
  const [name, setName] = useState<string | undefined>();
  const [email, setEmail] = useState<string | undefined>();
  const [cap, setCap] = useState<string | undefined>();

  if (settings.isLoading) return <p>Loading…</p>;
  if (!settings.data) return <p>No settings.</p>;
  const cur = settings.data;

  function save() {
    const body: Record<string, unknown> = {};
    if (name !== undefined && name !== (cur.recruiter_name ?? ""))
      body.recruiter_name = name;
    if (email !== undefined && email !== (cur.recruiter_email ?? ""))
      body.recruiter_email = email;
    if (cap !== undefined) body.monthly_llm_spend_cap_usd = Number(cap);
    update.mutate(body);
  }

  return (
    <div className="space-y-4 max-w-md">
      <div className="space-y-2">
        <Label>Recruiter name</Label>
        <Input
          value={name ?? cur.recruiter_name ?? ""}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label>Recruiter email</Label>
        <Input
          type="email"
          value={email ?? cur.recruiter_email ?? ""}
          onChange={(e) => setEmail(e.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label>Monthly LLM spend cap (USD)</Label>
        <Input
          type="number"
          min="0"
          value={cap ?? cur.monthly_llm_spend_cap_usd?.toString() ?? ""}
          onChange={(e) => setCap(e.target.value)}
        />
      </div>
      <Button onClick={save} disabled={update.isPending}>
        {update.isPending ? "Saving…" : "Save"}
      </Button>
    </div>
  );
}
