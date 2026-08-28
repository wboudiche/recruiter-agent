import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError } from "@/lib/api";
import {
  useCreateUser, useResetPassword, useUpdateUser, useUsers,
} from "@/hooks/use-users";

const ROLES = ["admin", "recruiter", "viewer"] as const;
type RoleValue = (typeof ROLES)[number];

const ROLE_LABELS: Record<RoleValue, string> = {
  admin: "Admin",
  recruiter: "Recruiter",
  viewer: "Viewer",
};

function fail(err: unknown, fallback: string) {
  // Surfaces the server's 409 guard-rail text ("this is the last active
  // admin — promote another admin first", "you cannot deactivate
  // yourself") verbatim, rather than replacing it with a generic message
  // that hides why the action was refused.
  toast.error(err instanceof ApiError ? err.detail : fallback);
}

export function UsersTab() {
  const users = useUsers();
  const createUser = useCreateUser();
  const updateUser = useUpdateUser();
  const resetPassword = useResetPassword();
  const [form, setForm] = useState({
    email: "", name: "", role: "recruiter" as string, password: "",
  });

  // Both row actions share these two mutation instances across every row,
  // so disabling on their .isPending prevents a second click (on this row
  // or another) from firing while a request is in flight.
  const rowBusy = updateUser.isPending || resetPassword.isPending;

  return (
    <div className="space-y-8 max-w-2xl">
      <div className="space-y-3">
        <h3 className="font-medium">Users</h3>
        <p className="text-xs text-muted-foreground">
          Viewers get read-only access — they can browse jobs and candidates
          but can't create, edit, or move anything.
        </p>
        {users.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {(users.data ?? []).map((u) => (
                <tr key={u.id} className="border-b">
                  <td className="py-2 pr-2 align-top">
                    <div>{u.email}</div>
                    <div className="text-xs text-muted-foreground">{u.name ?? "—"}</div>
                  </td>
                  <td className="py-2 pr-2 align-top w-40">
                    <Select
                      value={u.role}
                      disabled={rowBusy}
                      onValueChange={(value) =>
                        updateUser.mutate(
                          { id: u.id, role: value },
                          { onError: (err) => fail(err, "Could not change role") },
                        )
                      }
                    >
                      <SelectTrigger aria-label={`Role for ${u.email}`}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {ROLES.map((r) => (
                          <SelectItem key={r} value={r}>{ROLE_LABELS[r]}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </td>
                  <td className="py-2 pr-2 align-top text-xs text-muted-foreground">
                    {u.is_active ? "active" : "inactive"}
                  </td>
                  <td className="py-2 align-top space-x-2 whitespace-nowrap">
                    <Button
                      size="sm"
                      variant="outline"
                      aria-label={`${u.is_active ? "Deactivate" : "Reactivate"} ${u.email}`}
                      disabled={rowBusy}
                      onClick={() =>
                        updateUser.mutate(
                          { id: u.id, is_active: !u.is_active },
                          { onError: (err) => fail(err, "Could not update user") },
                        )
                      }
                    >
                      {u.is_active ? "Deactivate" : "Reactivate"}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      aria-label={`Reset password for ${u.email}`}
                      disabled={rowBusy}
                      onClick={() => {
                        const pw = window.prompt(`New password for ${u.email}`);
                        if (!pw) return;
                        resetPassword.mutate(
                          { id: u.id, password: pw },
                          {
                            onSuccess: () =>
                              toast.success("Password reset — their sessions were ended"),
                            onError: (err) => fail(err, "Could not reset password"),
                          },
                        );
                      }}
                    >
                      Reset password
                    </Button>
                  </td>
                </tr>
              ))}
              {(users.data ?? []).length === 0 && (
                <tr>
                  <td colSpan={4} className="py-4 text-sm text-muted-foreground">
                    No users yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      <form
        className="space-y-3 max-w-sm"
        onSubmit={(e) => {
          e.preventDefault();
          // The backend's `name` field is optional and nullable; sending
          // "" would store an empty string instead of leaving it unset.
          const trimmedName = form.name.trim();
          createUser.mutate(
            {
              email: form.email,
              role: form.role,
              password: form.password,
              ...(trimmedName ? { name: trimmedName } : {}),
            },
            {
              onSuccess: () => {
                toast.success("User created");
                setForm({ email: "", name: "", role: "recruiter", password: "" });
              },
              onError: (err) => fail(err, "Could not create user"),
            },
          );
        }}
      >
        <h3 className="font-medium">Add user</h3>
        <div className="space-y-2">
          <Label htmlFor="new-user-email">Email</Label>
          <Input
            id="new-user-email"
            aria-label="Email"
            type="email"
            required
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="new-user-name">Name (optional)</Label>
          <Input
            id="new-user-name"
            aria-label="Name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="new-user-role">Role</Label>
          <Select
            value={form.role}
            onValueChange={(value) => setForm({ ...form, role: value })}
          >
            <SelectTrigger id="new-user-role" aria-label="Role">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ROLES.map((r) => (
                <SelectItem key={r} value={r}>{ROLE_LABELS[r]}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="new-user-password">Initial password</Label>
          <Input
            id="new-user-password"
            aria-label="Initial password"
            type="password"
            required
            minLength={8}
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
        </div>
        <Button type="submit" disabled={createUser.isPending}>
          {createUser.isPending ? "Adding…" : "Add user"}
        </Button>
      </form>
    </div>
  );
}
