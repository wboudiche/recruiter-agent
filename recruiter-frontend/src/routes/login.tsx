import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { api, ApiError } from "@/lib/api";

interface AuthMethods {
  oidc: boolean;
  password: boolean;
}

const BASE_URL = import.meta.env.VITE_API_URL ?? "";

// Client-side mirror of the backend's `_safe_next` (recruiter/api/auth.py).
// `next` comes straight off the URL, so an attacker can set it to an
// absolute or protocol-relative URL to turn this page into an open
// redirect. The password-login response is a bare 204 (no body to read a
// server-validated redirect back from — see the docstring on `onSubmit`),
// so this page must sanitize `next` itself before navigating to it.
function safeNextPath(value: string): string {
  if (!value.startsWith("/")) return "/";
  if (value.startsWith("//") || value.startsWith("/\\")) return "/";
  return value;
}

// Editorial cinematic styling — the layout and motion are kept in-file so the
// aesthetic doesn't bleed into the rest of the app. The COLOURS, though, come
// from theme-palettes.css via <html>, so this page follows the theme toggle
// like every other route. (It used to redeclare --ed-* as hex on :root, which
// both froze it to dark and leaked those names app-wide.)
//
// The shared tokens are bare HSL triplets, not colours, so they need hsl()
// wrapping at each use. These local aliases do it once.
const STYLE = `
.ed-page, .ed-loading {
  --ink: hsl(var(--ed-cream));
  --ink-dim: hsl(var(--ed-cream-dim));
  --gold: hsl(var(--ed-amber));
  --gold-dim: hsl(var(--ed-amber) / 0.35);
  --hairline: hsl(var(--ed-cream) / 0.14);
  --ground: hsl(var(--ed-bg));
}

.ed-page {
  min-height: 100dvh;
  width: 100%;
  position: relative;
  overflow: hidden;
  color: var(--ink);
  font-family: "Manrope", "Helvetica Neue", system-ui, sans-serif;
  font-weight: 300;
  letter-spacing: 0.005em;
  isolation: isolate;
}

.ed-bg-photo {
  position: absolute;
  inset: 0;
  background:
    url("https://images.unsplash.com/photo-1497366811353-6870744d04b2?auto=format&fit=crop&w=2400&q=85")
      center / cover no-repeat;
  filter: grayscale(0.4) contrast(1.05);
  opacity: 0.45;
  z-index: -3;
}

.ed-bg-tint {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(60% 80% at 18% 18%, hsl(var(--ed-amber) / 0.18) 0%, transparent 60%),
    radial-gradient(80% 60% at 82% 90%, hsl(var(--ed-wine) / 0.85) 0%, transparent 70%),
    linear-gradient(135deg, hsl(var(--ed-bg-deep) / 0.92) 0%, hsl(var(--ed-bg-deep) / 0.6) 45%, hsl(var(--ed-bg-deep) / 0.95) 100%);
  z-index: -2;
}

.ed-grain {
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.12;
  mix-blend-mode: overlay;
  z-index: -1;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='220' height='220'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.7 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>");
}

.ed-shell {
  position: relative;
  min-height: 100dvh;
  display: grid;
  grid-template-rows: auto 1fr auto;
  /* Slimmer top/bottom so the form fits a 720-800px laptop viewport
     without scrolling. */
  padding: 14px clamp(24px, 5vw, 72px);
  gap: 0;
}

.ed-hairline-top, .ed-hairline-bot {
  height: 1px;
  background: linear-gradient(to right, transparent, var(--hairline) 12%, var(--hairline) 88%, transparent);
}

.ed-topbar, .ed-botbar {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 12px 0;
  font-size: 11px;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: var(--ink-dim);
}

.ed-wordmark {
  font-family: "Fraunces", "Times New Roman", serif;
  font-style: italic;
  font-weight: 400;
  font-size: 18px;
  letter-spacing: 0;
  text-transform: none;
  color: var(--ink);
}
.ed-wordmark .dot {
  color: var(--gold);
  margin: 0 6px;
}

.ed-stage {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr);
  align-items: center;
  gap: clamp(24px, 6vw, 96px);
  /* Vertical padding tracks viewport height but caps lower (was 72px). */
  padding: clamp(12px, 3vh, 40px) 0;
}

.ed-left {
  position: relative;
}

.ed-kicker {
  font-size: 11px;
  letter-spacing: 0.32em;
  text-transform: uppercase;
  color: var(--gold);
  margin-bottom: 18px;
  display: inline-flex;
  align-items: center;
  gap: 12px;
}
.ed-kicker::before {
  content: "";
  width: 28px;
  height: 1px;
  background: var(--gold);
  display: inline-block;
}

.ed-headline {
  font-family: "Fraunces", "Times New Roman", serif;
  font-variation-settings: "opsz" 144, "SOFT" 30;
  font-style: italic;
  font-weight: 400;
  /* Capped from 168 → 112 so the four-line headline doesn't dominate
     a typical laptop screen (720-800px tall). Min unchanged. */
  font-size: clamp(56px, 8vw, 112px);
  line-height: 0.92;
  letter-spacing: -0.035em;
  color: var(--ink);
  margin: 0;
}
.ed-headline .accent {
  color: var(--gold);
  font-style: italic;
}
.ed-headline .stroke {
  -webkit-text-stroke: 1.5px var(--ink);
  color: transparent;
  font-style: italic;
}

.ed-sub {
  margin-top: 20px;
  max-width: 460px;
  font-size: 14px;
  line-height: 1.5;
  color: var(--ink-dim);
  font-weight: 300;
}

.ed-meta {
  margin-top: 28px;
  display: grid;
  grid-template-columns: repeat(3, max-content);
  gap: 32px;
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--ink-dim);
}
.ed-meta strong {
  display: block;
  font-family: "Fraunces", serif;
  font-style: italic;
  font-weight: 400;
  font-size: 20px;
  letter-spacing: 0;
  text-transform: none;
  color: var(--ink);
  margin-top: 4px;
}

.ed-right {
  justify-self: end;
  width: 100%;
  max-width: 420px;
  position: relative;
}

.ed-card {
  position: relative;
  padding: 28px 32px;
  background: linear-gradient(180deg, hsl(var(--ed-bg-deep) / 0.55) 0%, hsl(var(--ed-bg-deep) / 0.75) 100%);
  border: 1px solid var(--gold-dim);
  backdrop-filter: blur(14px) saturate(120%);
  -webkit-backdrop-filter: blur(14px) saturate(120%);
  box-shadow:
    0 30px 80px -30px hsl(var(--ed-shadow) / var(--ed-shadow-strength)),
    inset 0 1px 0 hsl(var(--ed-cream) / 0.06);
}
.ed-card::before {
  content: "";
  position: absolute;
  top: -1px; left: -1px; right: -1px;
  height: 1px;
  background: linear-gradient(to right, transparent, var(--gold), transparent);
}

.ed-card-label {
  font-size: 10px;
  letter-spacing: 0.36em;
  text-transform: uppercase;
  color: var(--gold);
  margin-bottom: 8px;
}
.ed-card-title {
  font-family: "Fraunces", serif;
  font-style: italic;
  font-weight: 400;
  font-size: 24px;
  line-height: 1.1;
  letter-spacing: -0.01em;
  margin: 0 0 18px;
}

.ed-field {
  margin-bottom: 14px;
}
.ed-field label {
  display: block;
  font-size: 10px;
  letter-spacing: 0.28em;
  text-transform: uppercase;
  color: var(--ink-dim);
  margin-bottom: 8px;
}
.ed-input {
  width: 100%;
  background: transparent;
  border: none;
  border-bottom: 1px solid hsl(var(--ed-cream) / 0.2);
  color: var(--ink);
  font-family: "Manrope", sans-serif;
  font-size: 15px;
  font-weight: 300;
  letter-spacing: 0.01em;
  padding: 8px 0 10px;
  outline: none;
  transition: border-color 200ms ease;
}
.ed-input:focus {
  border-bottom-color: var(--gold);
}
.ed-input::placeholder {
  color: hsl(var(--ed-cream) / 0.3);
  font-style: italic;
}

/* ----- Light mode -----
   The photo and its tint were built to sit under a near-black wash. On
   parchment the same layers turn the page muddy, so the photo drops back and
   the tint inverts into a light wash. Structure is untouched. */
html.light .ed-bg-photo {
  opacity: 0.16;
  filter: grayscale(0.55) contrast(1.02);
}

html.light .ed-bg-tint {
  background:
    radial-gradient(60% 80% at 18% 18%, hsl(var(--ed-amber) / 0.10) 0%, transparent 60%),
    radial-gradient(80% 60% at 82% 90%, hsl(var(--ed-wine) / 0.14) 0%, transparent 70%),
    linear-gradient(135deg, hsl(var(--ed-bg-deep) / 0.94) 0%, hsl(var(--ed-bg) / 0.86) 45%, hsl(var(--ed-bg-deep) / 0.96) 100%);
}

html.light .ed-grain {
  /* White noise under 'overlay' is inert on a light ground — see the same
     swap in geist-theme.css. */
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='220' height='220'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.7 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>");
  mix-blend-mode: multiply;
  opacity: 0.05;
}

.ed-topbar-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.ed-theme-toggle button {
  height: 26px;
  width: 26px;
  padding: 0;
  border-radius: 0;
  background: transparent;
  border: 1px solid var(--gold-dim);
  color: var(--gold);
  transition: border-color 200ms ease, color 200ms ease;
}
.ed-theme-toggle button:hover {
  border-color: var(--gold);
  background: transparent;
}

.ed-error {
  font-family: "Fraunces", serif;
  font-style: italic;
  font-size: 13px;
  color: var(--gold);
  margin: -6px 0 18px;
  padding-left: 14px;
  border-left: 1px solid var(--gold);
}

.ed-submit {
  width: 100%;
  padding: 13px 24px;
  background: var(--ink);
  color: var(--ground);
  border: none;
  font-family: "Manrope", sans-serif;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.32em;
  text-transform: uppercase;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: background 200ms ease, color 200ms ease, letter-spacing 250ms ease;
}
.ed-submit:hover:not(:disabled) {
  background: var(--gold);
  letter-spacing: 0.38em;
}
.ed-submit:disabled {
  opacity: 0.5;
  cursor: wait;
}
.ed-submit .arrow {
  font-family: "Fraunces", serif;
  font-style: italic;
  font-weight: 400;
  font-size: 22px;
  letter-spacing: 0;
  text-transform: none;
}

.ed-divider {
  display: flex;
  align-items: center;
  gap: 14px;
  margin: 18px 0 12px;
  color: var(--ink-dim);
  font-size: 10px;
  letter-spacing: 0.4em;
  text-transform: uppercase;
}
.ed-divider::before, .ed-divider::after {
  content: "";
  flex: 1;
  height: 1px;
  background: var(--hairline);
}

.ed-sso {
  width: 100%;
  padding: 11px 24px;
  background: transparent;
  color: var(--ink);
  border: 1px solid var(--hairline);
  font-family: "Manrope", sans-serif;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.32em;
  text-transform: uppercase;
  cursor: pointer;
  transition: border-color 200ms ease, color 200ms ease;
}
.ed-sso:hover {
  border-color: var(--gold);
  color: var(--gold);
}

.ed-fineprint {
  margin-top: 16px;
  font-family: "Fraunces", serif;
  font-style: italic;
  font-size: 11px;
  color: var(--ink-dim);
  line-height: 1.5;
}
.ed-fineprint .num {
  color: var(--gold);
  font-style: normal;
  font-family: "Manrope", sans-serif;
  letter-spacing: 0.16em;
  font-size: 10px;
  padding-right: 8px;
}

/* staggered reveal */
@keyframes edRise {
  from { opacity: 0; transform: translateY(18px); }
  to { opacity: 1; transform: translateY(0); }
}
.ed-rise {
  animation: edRise 900ms cubic-bezier(0.22, 1, 0.36, 1) both;
}

.ed-loading {
  min-height: 100vh;
  display: grid;
  place-items: center;
  font-family: "Fraunces", serif;
  font-style: italic;
  font-size: 18px;
  color: var(--ink-dim);
  background: var(--ground);
}

@media (max-width: 820px) {
  .ed-stage {
    grid-template-columns: 1fr;
    gap: 32px;
  }
  .ed-right { justify-self: stretch; max-width: none; }
  .ed-meta { grid-template-columns: 1fr 1fr; gap: 20px; }
  .ed-headline { font-size: clamp(56px, 14vw, 96px); }
}
`;

export default function Login() {
  const [params] = useSearchParams();
  const next = params.get("next") ?? "/";

  const [methods, setMethods] = useState<AuthMethods | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<AuthMethods>("/api/auth/methods").then(setMethods).catch(() => {
      setMethods({ oidc: false, password: false });
    });
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      // Password login returns a bare 204 on success (no body — the users-
      // table login/deactivation/require_role work in the backend
      // deliberately dropped the old {"redirect": ...} response). `next`
      // is already in hand from the URL this page was loaded with, so
      // navigate to it directly rather than reading anything back — the
      // backend has no use for `next` either (it never sanitizes a
      // redirect for this endpoint), so it isn't sent.
      await api("/api/auth/login/password", {
        method: "POST",
        json: { email, password },
        noAuthRedirect: true,
      });
      window.location.href = safeNextPath(next);
    } catch (err) {
      const msg =
        err instanceof ApiError && err.status === 401
          ? "Those credentials don't match what's on file."
          : err instanceof ApiError && err.status === 429
            ? "Too many attempts. Step back for a moment."
            : "Something went sideways. Try again.";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  function onSsoClick() {
    const safeNext = encodeURIComponent(next);
    window.location.href = `${BASE_URL}/api/auth/login?next=${safeNext}`;
  }

  if (methods === null) {
    return (
      <>
        <style>{STYLE}</style>
        <div className="ed-loading">loading…</div>
      </>
    );
  }

  return (
    <>
      <style>{STYLE}</style>
      <div className="ed-page">
        <div className="ed-bg-photo" />
        <div className="ed-bg-tint" />
        <div className="ed-grain" />

        <div className="ed-shell">
          <div>
            <div className="ed-topbar ed-rise" style={{ animationDelay: "60ms" }}>
              <span className="ed-wordmark">
                Recruiter<span className="dot">·</span>
                <span style={{ fontStyle: "normal", fontFamily: "Manrope", fontSize: 11, letterSpacing: "0.32em", textTransform: "uppercase" }}>
                  Agent
                </span>
              </span>
              <span className="ed-topbar-right">
                <span>Issue №01 · MMXXVI</span>
                <span className="ed-theme-toggle">
                  <ThemeToggle />
                </span>
              </span>
            </div>
            <div className="ed-hairline-top" />
          </div>

          <main className="ed-stage">
            <section className="ed-left">
              <div className="ed-kicker ed-rise" style={{ animationDelay: "160ms" }}>
                Sign in to continue
              </div>

              <h1 className="ed-headline ed-rise" style={{ animationDelay: "240ms" }}>
                Hire
                <br />
                <span className="accent">deliberately,</span>
                <br />
                <span className="stroke">at the speed</span>
                <br />
                of trust.
              </h1>

              <p className="ed-sub ed-rise" style={{ animationDelay: "420ms" }}>
                Recruiter Agent is the quiet room behind every shortlist —
                criteria, conversation, and consequence, kept in one place.
              </p>

              <div className="ed-meta ed-rise" style={{ animationDelay: "560ms" }}>
                <div>
                  Open roles
                  <strong>06</strong>
                </div>
                <div>
                  In-flight
                  <strong>12</strong>
                </div>
                <div>
                  Hired this qtr.
                  <strong>04</strong>
                </div>
              </div>
            </section>

            <aside className="ed-right ed-rise" style={{ animationDelay: "320ms" }}>
              <div className="ed-card">
                <div className="ed-card-label">Members entrance</div>
                <h2 className="ed-card-title">Welcome back.</h2>

                {methods.password ? (
                  <form onSubmit={onSubmit} noValidate>
                    <div className="ed-field">
                      <label htmlFor="email">Email</label>
                      <input
                        id="email"
                        className="ed-input"
                        type="email"
                        autoComplete="username"
                        placeholder="you@company"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        required
                      />
                    </div>
                    <div className="ed-field">
                      <label htmlFor="password">Password</label>
                      <input
                        id="password"
                        className="ed-input"
                        type="password"
                        autoComplete="current-password"
                        placeholder="••••••••"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        required
                      />
                    </div>
                    {error ? (
                      <p className="ed-error" role="alert">
                        {error}
                      </p>
                    ) : null}
                    <button type="submit" className="ed-submit" disabled={submitting}>
                      <span>{submitting ? "signing in" : "sign in"}</span>
                      <span className="arrow">→</span>
                    </button>
                  </form>
                ) : null}

                {methods.oidc && methods.password ? (
                  <div className="ed-divider">or</div>
                ) : null}

                {methods.oidc ? (
                  <button type="button" className="ed-sso" onClick={onSsoClick}>
                    Continue with SSO
                  </button>
                ) : null}

                {!methods.oidc && !methods.password ? (
                  <p className="ed-error" role="alert">
                    No sign-in method is configured. Speak to your administrator.
                  </p>
                ) : null}

                <p className="ed-fineprint">
                  <span className="num">01</span>
                  Session lasts seven days. Cookies are http-only and same-site.
                </p>
              </div>
            </aside>
          </main>

          <div>
            <div className="ed-hairline-bot" />
            <div className="ed-botbar ed-rise" style={{ animationDelay: "680ms" }}>
              <span>© MMXXVI · Recruiter Agent</span>
              <span>single-tenant · self-hosted</span>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
