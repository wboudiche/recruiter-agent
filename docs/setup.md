# Recruiter Agent — Setup

## Auth setup (OIDC SSO)

The app uses OIDC SSO for authentication. Configure your IdP via env vars:

```
RECRUITER_OIDC_ISSUER=https://accounts.google.com
RECRUITER_OIDC_CLIENT_ID=<from IdP console>
RECRUITER_OIDC_CLIENT_SECRET=<from IdP console>
RECRUITER_OIDC_REDIRECT_URI=http://localhost:8765/api/auth/callback
RECRUITER_OIDC_ALLOWED_DOMAINS=acme.com
RECRUITER_SECURE_COOKIES=false   # localhost is HTTP-only
```

For Google Workspace specifically:

1. Google Cloud Console → APIs & Services → Credentials → Create OAuth 2.0 Client ID (Web application).
2. Authorized redirect URI: `http://localhost:8765/api/auth/callback` (dev), `https://recruiter.<your-host>/api/auth/callback` (prod).
3. Authorized JavaScript origins: `http://localhost:5173` (dev).
4. Copy the client ID and secret into the env vars above.
5. The app sends `hd=<your-domain>` to Google when there's exactly one allowed domain — restricts the consent screen to that Workspace tenant.

### Dev escape hatch

For tests and offline dev, set:

```
RECRUITER_DEV_AUTH_BYPASS=walid@acme.com
RECRUITER_OIDC_ISSUER=
```

The bypass auto-creates a synthetic user with that email. **It only activates when `RECRUITER_OIDC_ISSUER` is empty** — a misconfigured prod that leaves `RECRUITER_DEV_AUTH_BYPASS` set but also configures the IdP falls through to OIDC, which is the right failure mode.

### Prod posture

- Set `RECRUITER_SECURE_COOKIES=true` (HTTPS only).
- Verify `RECRUITER_DEV_AUTH_BYPASS` is unset.
- Update IdP redirect URI and allowed origins to the prod hostname.

## Sourcing providers

Web/LinkedIn search supports three providers; pick one in **Settings → Sourcing**.

### Google Custom Search

- Free 100 queries/day. Requires a Google Cloud project with a billing account attached (the trial 300$ counts).
- Setup:
  1. https://cse.google.com → New search engine → enable "Search the entire web". Copy the **Search engine ID (cx)**.
  2. https://console.cloud.google.com/apis/library/customsearch.googleapis.com → Enable.
  3. https://console.cloud.google.com/apis/credentials → Create credentials → API key. Copy the `AIza…`.
  4. Settings → Sourcing → paste API key + CX → Save.

### Brave Search

- Free 2000 queries/month, no card required.
- Setup:
  1. https://brave.com/search/api/ → sign up → copy the API key (`brv_…`).
  2. Settings → Sourcing → Provider: **Brave Search** → paste API key → Save.

### SerpAPI (Google)

- Returns Google SERPs without a Google billing account. Free 100 searches/month, no card required.
- Setup:
  1. https://serpapi.com → sign up → copy the API key from the dashboard.
  2. Settings → Sourcing → Provider: **SerpAPI (Google)** → paste API key → Save.

### SearXNG (self-hosted)

- Unlimited; runs locally on your machine.
- Setup:
  1. Create a host directory for the config:
     ```
     mkdir -p ~/searxng && cat > ~/searxng/settings.yml <<'YAML'
     use_default_settings: true
     search:
       formats:
         - html
         - json
     server:
       secret_key: "change-me"
     YAML
     ```
     The bare `searxng/searxng` image ships with `formats: [html]` only — JSON must be enabled explicitly or the provider will return non-JSON and the app will surface a clear error.
  2. Run the container with that config mounted:
     ```
     docker run --rm -p 8080:8080 \
       -v ~/searxng:/etc/searxng \
       -e SEARXNG_BASE_URL=http://localhost:8080/ \
       searxng/searxng
     ```
  3. Settings → Sourcing → Provider: **SearXNG (self-hosted)** → Instance URL: `http://localhost:8080` → Save.

### GitHub (separate, for the GitHub tab)

- Works without configuration (60 requests/hour anonymously).
- Optional: Settings → Sourcing → paste a GitHub personal access token (`ghp_…`) to raise the limit to 5000/hour.

## Candidate enrichment

Enrichment fetches public profile data from up to 10 sources (GitHub, Stack Overflow,
Hacker News, Reddit, Mastodon, Bluesky, Dev.to, YouTube, Twitter/X, blog/website)
and surfaces it on the candidate detail page so the recruiter can review the
candidate's public technical and social presence.

**Important: enrichment never reaches the LLM scorer.** The score is computed from
the resume only, identical to before. Enrichment is a research aid for the recruiter.

### Enabling

1. Settings → Enrichment → tick **Enable enrichment**.
2. Per source, leave the checkbox ticked (default) or untick to skip that source.
3. For paid / keyed sources:
   - **Twitter / X**: requires X API v2 Basic (~$200/month). Paste the bearer token.
   - **YouTube**: free 10k units/day from Google Cloud. Paste the API key.
   - **Stack Exchange** (optional): raises the per-IP quota from 300/d to 10k/d.
4. **GitHub**: reuses the GitHub token from the Sourcing tab — no separate field.

### Per-job consent

Each Job has an `enrichment_consent` checkbox. **Default off.**

When `false`:
- Only URLs the candidate explicitly listed in their resume are enriched.
- No discovery searches run.
- Twitter/X is skipped entirely.

When `true`:
- Discovery searches run (`"<name>" "<employer>" site:<domain>` per provider, via the
  active sourcing provider). Costs roughly 8–15 sourcing API calls per candidate.
- All providers including Twitter/X are eligible.

The label reads:

> Process the candidate's public technical and social presence for scoring.
> Required where applicable law (e.g., GDPR Art. 6 + 9) demands lawful basis.

### TTL & re-enrich

Bundles are persisted on `Application.enrichment` with a 30-day TTL. Within TTL,
retries reuse the cache. To refresh on demand, click **Re-enrich now** on the
candidate detail page; this clears the bundle and re-runs the pipeline.

### Failure modes

- A failed source logs `enrichment.failed` and shows up in the per-source error
  rows under the enrichment section, but never blocks scoring.
- If the master toggle is off, the enrichment stage no-ops and the pipeline
  proceeds as before.
- If the per-job consent is off, only `candidate.links` are enriched.
