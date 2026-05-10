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

### SearXNG (self-hosted)

- Unlimited; runs locally on your machine.
- Setup:
  1. `docker run --rm -p 8080:8080 -e BASE_URL=http://localhost:8080 searxng/searxng`
  2. In the running container, edit `/etc/searxng/settings.yml` to ensure `search.formats` contains `json` (the default config in the image already has it).
  3. Settings → Sourcing → Provider: **SearXNG (self-hosted)** → Instance URL: `http://localhost:8080` → Save.

### GitHub (separate, for the GitHub tab)

- Works without configuration (60 requests/hour anonymously).
- Optional: Settings → Sourcing → paste a GitHub personal access token (`ghp_…`) to raise the limit to 5000/hour.
