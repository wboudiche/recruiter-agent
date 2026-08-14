import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError } from "@/lib/api";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useSettings, useUpdateSettings } from "@/hooks/use-settings";

export function ProfileTab() {
  const me = useCurrentUser();
  const isAdmin = me.data?.role === "admin";

  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const changePassword = useMutation({
    mutationFn: () => api("/api/auth/password", { method: "POST", json: pw }),
    onSuccess: () => {
      toast.success("Password changed");
      setPw({ current_password: "", new_password: "" });
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Could not change password"),
  });

  return (
    <div className="space-y-8 max-w-md">
      {/* `PUT /api/settings` is admin-only (Task 3), and every field below
          saves through it. Non-admins never had a use for these fields as
          individual "profile" settings — recruiter_name/email is the
          org-wide sender identity, not a per-user setting — so the section
          is hidden rather than shown-then-403'd. The `me.data &&` guard
          holds the explanatory line back until the role is actually known,
          so an admin doesn't see it flash during the initial fetch. */}
      {isAdmin ? (
        <RecruiterProfileSection />
      ) : (
        me.data && (
          <p className="text-xs text-muted-foreground">
            Integration and workspace settings are managed by an admin.
          </p>
        )
      )}

      <section className="space-y-2">
        <h3 className="font-medium">Change password</h3>
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            changePassword.mutate();
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="current-password">Current password</Label>
            <Input
              id="current-password"
              aria-label="Current password"
              type="password"
              required
              value={pw.current_password}
              onChange={(e) => setPw({ ...pw, current_password: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new-password">New password</Label>
            <Input
              id="new-password"
              aria-label="New password"
              type="password"
              required
              minLength={8}
              value={pw.new_password}
              onChange={(e) => setPw({ ...pw, new_password: e.target.value })}
            />
          </div>
          <Button type="submit" disabled={changePassword.isPending}>
            {changePassword.isPending ? "Changing…" : "Change password"}
          </Button>
        </form>
      </section>
    </div>
  );
}

function RecruiterProfileSection() {
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
    <section className="space-y-4">
      <h3 className="font-medium">Recruiter profile</h3>
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
    </section>
  );
}
