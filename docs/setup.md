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
