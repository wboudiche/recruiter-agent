import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";

interface StatusResponse {
  connected: boolean;
  set_at: string | null;
  auto_reconnect_enabled: boolean;
}

interface ConnectResponse {
  status: "connected" | "challenge" | "failed";
  reason: string | null;
  set_at: string | null;
}

const STATUS_KEY = ["sourcing", "linkedin", "status"] as const;

type Mode = "credentials" | "cookie";

export function LinkedInConnect() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Mode>("credentials");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [cookie, setCookie] = useState("");
  const [warning, setWarning] = useState<string | null>(null);

  const status = useQuery({
    queryKey: STATUS_KEY,
    queryFn: () => api<StatusResponse>("/api/sourcing/linkedin/status"),
  });

  const connect = useMutation({
    mutationFn: () =>
      api<ConnectResponse>("/api/sourcing/linkedin/connect", {
        method: "POST",
        json: { email, password, remember },
        noAuthRedirect: true,
      }),
    onSuccess: (resp) => {
      if (resp.status === "connected") {
        toast.success(
          remember ? "LinkedIn connected (auto-reconnect on)" : "LinkedIn connected",
        );
        setOpen(false);
        setEmail("");
        setPassword("");
        setRemember(false);
        setWarning(null);
        qc.invalidateQueries({ queryKey: STATUS_KEY });
      } else {
        setWarning(resp.reason ?? "Login failed.");
      }
    },
    onError: (err) => {
      setWarning(err instanceof ApiError ? err.detail : "Login failed.");
    },
  });

  const connectCookie = useMutation({
    mutationFn: () =>
      api<ConnectResponse>("/api/sourcing/linkedin/connect-cookie", {
        method: "POST",
        json: { li_at: cookie.trim() },
        noAuthRedirect: true,
      }),
    onSuccess: (resp) => {
      if (resp.status === "connected") {
        toast.success("LinkedIn connected");
        setOpen(false);
        setCookie("");
        setWarning(null);
        qc.invalidateQueries({ queryKey: STATUS_KEY });
      } else {
        setWarning(resp.reason ?? "Cookie rejected.");
      }
    },
    onError: (err) => {
      setWarning(err instanceof ApiError ? err.detail : "Cookie rejected.");
    },
  });

  const disconnect = useMutation({
    mutationFn: () =>
      api("/api/sourcing/linkedin/disconnect", { method: "POST" }),
    onSuccess: () => {
      toast.success("LinkedIn disconnected");
      qc.invalidateQueries({ queryKey: STATUS_KEY });
    },
  });

  const set_at = status.data?.set_at ? new Date(status.data.set_at) : null;

  function openModal() {
    setMode("credentials");
    setEmail("");
    setPassword("");
    setCookie("");
    setRemember(status.data?.auto_reconnect_enabled ?? false);
    setWarning(null);
    setOpen(true);
  }

  const pending = connect.isPending || connectCookie.isPending;

  return (
    <section className="space-y-2 border border-border p-4">
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <h3 className="font-serif italic text-lg leading-tight">
            LinkedIn auto-extraction
          </h3>
          <p className="text-xs text-muted-foreground mt-1 max-w-prose leading-relaxed">
            Sign in once with your LinkedIn credentials — we drive a headless
            browser through the login flow, capture the resulting session
            cookie, and discard the password. The cookie is the only thing
            stored (encrypted). Reconnect when LinkedIn throttles or signs
            you out.
          </p>
        </div>
        <div className="shrink-0">
          {status.isLoading ? (
            <Spinner size={14} />
          ) : status.data?.connected ? (
            <span className="text-[10px] uppercase tracking-[0.28em] text-[hsl(var(--ed-amber))] border border-[hsl(var(--ed-amber)/0.4)] px-2 py-1">
              {status.data.auto_reconnect_enabled
                ? "Connected · auto"
                : "Connected"}
            </span>
          ) : status.data?.auto_reconnect_enabled ? (
            <span
              className="text-[10px] uppercase tracking-[0.28em] text-[hsl(var(--ed-amber))] border border-[hsl(var(--ed-amber)/0.4)] px-2 py-1"
              title="Cookie was cleared after a challenge; auto-reconnect creds are still stored. Next scrape will retry."
            >
              Awaiting reconnect
            </span>
          ) : (
            <span className="text-[10px] uppercase tracking-[0.28em] text-muted-foreground border border-border px-2 py-1">
              Not connected
            </span>
          )}
        </div>
      </div>

      {set_at && (
        <p className="text-xs text-muted-foreground">
          Cookie set {set_at.toLocaleString()}.
        </p>
      )}

      <div className="flex items-center gap-2 pt-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={openModal}
        >
          {status.data?.connected ? "Reconnect" : "Connect LinkedIn"}
        </Button>
        {status.data?.connected && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => disconnect.mutate()}
            disabled={disconnect.isPending}
          >
            Disconnect
          </Button>
        )}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Connect LinkedIn</DialogTitle>
            <DialogDescription>
              {mode === "credentials"
                ? "Your password is consumed once and not persisted (unless you tick remember below). Only the resulting li_at session cookie is stored, encrypted."
                : "Paste an existing li_at cookie value from your browser's devtools. Cookie is stored encrypted; no password is ever involved."}
            </DialogDescription>
          </DialogHeader>

          {/* Mode toggle */}
          <div className="flex border border-border" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={mode === "credentials"}
              className={`flex-1 py-2 text-[11px] uppercase tracking-[0.22em] transition-colors ${
                mode === "credentials"
                  ? "bg-[hsl(var(--ed-bg-deep)/0.8)] text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => {
                setMode("credentials");
                setWarning(null);
              }}
              disabled={pending}
            >
              Email + password
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "cookie"}
              className={`flex-1 py-2 text-[11px] uppercase tracking-[0.22em] transition-colors ${
                mode === "cookie"
                  ? "bg-[hsl(var(--ed-bg-deep)/0.8)] text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => {
                setMode("cookie");
                setWarning(null);
              }}
              disabled={pending}
            >
              Paste cookie
            </button>
          </div>

          <div className="space-y-3 py-2">
            {mode === "credentials" ? (
              <>
                <div className="space-y-1">
                  <Label htmlFor="li-email">Email</Label>
                  <Input
                    id="li-email"
                    type="email"
                    autoComplete="username"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    disabled={pending}
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="li-password">Password</Label>
                  <Input
                    id="li-password"
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    disabled={pending}
                  />
                </div>
                <label className="flex items-start gap-2 text-xs text-muted-foreground leading-snug cursor-pointer pt-1">
                  <input
                    type="checkbox"
                    checked={remember}
                    onChange={(e) => setRemember(e.target.checked)}
                    disabled={pending}
                    className="mt-0.5 accent-[hsl(var(--ed-amber))]"
                  />
                  <span>
                    <span className="text-foreground font-medium">
                      Remember password for auto-reconnect.
                    </span>{" "}
                    Encrypted at rest. The backend will silently re-log-in
                    when LinkedIn invalidates the cookie. Trade-off:
                    password sits in the database (encrypted) instead of
                    being dropped after this call. Disconnect clears it.
                  </span>
                </label>
              </>
            ) : (
              <div className="space-y-1">
                <Label htmlFor="li-cookie">li_at cookie value</Label>
                <Textarea
                  id="li-cookie"
                  rows={4}
                  placeholder="AQED…"
                  value={cookie}
                  onChange={(e) => setCookie(e.target.value)}
                  disabled={pending}
                  className="font-mono text-xs"
                />
                <p className="text-xs text-muted-foreground leading-snug">
                  Get it from Chrome devtools → Application → Cookies →
                  https://www.linkedin.com → row <code>li_at</code>. We
                  validate it by opening linkedin.com/feed once — takes
                  ~5-10s.
                </p>
              </div>
            )}

            {warning && (
              <p
                className="text-sm font-serif italic text-[hsl(var(--ed-amber))] border-l border-[hsl(var(--ed-amber))] pl-3"
                role="alert"
              >
                {warning}
              </p>
            )}
            {pending && (
              <p className="flex items-center gap-2 text-xs text-muted-foreground">
                <Spinner size={12} />
                {mode === "credentials"
                  ? "Driving the LinkedIn login flow — this can take 15-30s."
                  : "Validating the cookie against linkedin.com — this can take 5-10s."}
              </p>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={pending}
            >
              Cancel
            </Button>
            {mode === "credentials" ? (
              <Button
                type="button"
                onClick={() => connect.mutate()}
                disabled={pending || !email || !password}
              >
                {connect.isPending ? "Connecting…" : "Connect"}
              </Button>
            ) : (
              <Button
                type="button"
                onClick={() => connectCookie.mutate()}
                disabled={pending || cookie.trim().length < 10}
              >
                {connectCookie.isPending ? "Validating…" : "Connect"}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
