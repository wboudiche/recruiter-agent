# Recruiter Agent

AI-assisted sourcing for individual recruiters and small teams. Add a candidate
from a URL, CV, paste, or search — the system extracts a structured profile,
enriches it from public sources, and scores it against your job's weighted
criteria. Everything runs locally in Docker against your own LLM and API keys.

## Quick start

Requires Docker. Default LLM is Anthropic; any OpenAI-compatible endpoint
(LINAGORA gateway, OpenRouter, Ollama, vLLM) also works.

```bash
git clone <repo> recruiter-agent && cd recruiter-agent
cp .env.example .env

# Generate the Fernet key that encrypts your stored API keys + cookies.
# Paste the output into .env as RECRUITER_SETTINGS_KEY=...
python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"

# Edit .env and fill in (compose refuses to start if any are blank):
#   POSTGRES_PASSWORD=<random>
#   RECRUITER_SETTINGS_KEY=<output above>
#   RECRUITER_DEFAULT_ACCOUNT_EMAIL=you@example.com
#   RECRUITER_DEFAULT_ACCOUNT_PASSWORD=<random>

docker compose up -d --build
# UI:   http://localhost:8088
# Docs: http://localhost:8088/docs
```

Log in with the admin credentials from `.env`, then open **Settings → LLM**
and paste your provider key. Everything else (Search, GitHub, LinkedIn, Apify,
SMTP) is optional; the system runs in increasingly capable modes as you
configure more keys.

> **Back up `RECRUITER_SETTINGS_KEY`.** Losing it makes every stored secret
> unrecoverable.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│              Browser — React 18 + Tailwind + SSE                  │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼  HTTPS · session cookie
┌──────────────────────────────────────────────────────────────────┐
│                  FastAPI (Python 3.12, async)                     │
│  ┌─────────────────────────┐    ┌───────────────────────────┐    │
│  │  Pipeline orchestrator   │    │  Conversational agent     │    │
│  │  fetch → extract → enrich│    │  LLM loop ↔ 11 tools      │    │
│  │  → score → persist       │    │  (read · search · action) │    │
│  └────────────┬─────────────┘    └─────────────┬─────────────┘    │
│               └────── emits stage / chat events ────┘             │
└──────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   ┌─────────┐         ┌───────────┐         ┌────────────┐
   │ Postgres│         │ LLM       │         │ Sources    │
   │ Alembic │         │ Anthropic │         │ Apify      │
   │ JSONB   │         │   or      │         │ Playwright │
   │         │         │ OpenAI    │         │ GitHub API │
   │         │         │ compat    │         │ Search APIs│
   └─────────┘         └───────────┘         └────────────┘
```

**Backend** lives under `src/recruiter/` (`api/` routers, `pipeline/` for
extraction/enrich/score, `sourcing/` for LinkedIn + search providers,
`agent/` for the conversational agent, `models/` SQLAlchemy, `crypto.py`
for at-rest secret encryption). **Frontend** is `recruiter-frontend/` (Vite +
React + TanStack Query). DB schema is managed by Alembic.

## The candidate pipeline

Each application moves through this finite-state machine:

```
extracting → enriching → scored → validated → invited → scheduled
                              ↘── rejected (terminal except unreject)
```

Stages live on the kanban; SSE pushes transitions so the UI updates without
refresh.

1. **Extracting** — fetch the source (LinkedIn via Apify or Playwright,
   GitHub via API, web via httpx + trafilatura, CV via pdf/docx parser),
   then call the LLM with a structured-output schema to pull name,
   headline, location, summary, skills, experience, education, links.
2. **Enriching** — fan out to per-source enrichers (GitHub repos, blog,
   Twitter/X, YouTube, Stack Exchange) gated by `enrichment.consent`.
3. **Scored** — for each criterion: LLM returns 0–100 with a per-criterion
   rationale, plus a weighted overall and one-sentence overall rationale.
4. **Validated / Invited / Scheduled / Rejected** — recruiter actions
   tracked with timestamps.

## The recruiter agent

Conversational LLM with 11 registered tools (read job/applications/criteria,
search the kanban, draft/send invitations, reject/validate, fetch enrichment,
re-enrich, edit criteria, etc.). Reversible actions go through an undo store
so you can roll back a wrong call.

Open the **Chat** panel on any candidate detail page.

## Configuration reference

All config is either an **env var** (read at startup, in `.env`) or a
**Settings row** (encrypted at rest, editable in `/settings`). Settings win
over env vars where both exist — except `RECRUITER_LINKEDIN_LI_AT`, where
env wins so dev overrides work.

### Env vars (required)

| Var | Purpose |
|---|---|
| `POSTGRES_PASSWORD` | Postgres role password. Threaded into the backend's DATABASE_URL. |
| `RECRUITER_SETTINGS_KEY` | Fernet key encrypting every `*_enc` column. Generate with the command in Quick start. **Back this up.** |
| `RECRUITER_DEFAULT_ACCOUNT_EMAIL` | Bootstrap admin login. Eager-seeded into `users` on startup if missing. |
| `RECRUITER_DEFAULT_ACCOUNT_PASSWORD` | Bootstrap password. Compared byte-for-byte at login time. |
| `RECRUITER_ALLOWED_ORIGINS` | Comma-separated browser origins (CSRF Origin allowlist). Default `http://localhost:8088`. |

### Env vars (optional)

| Var | Purpose |
|---|---|
| `RECRUITER_LINKEDIN_LI_AT` | LinkedIn `li_at` cookie. If set, **overrides** Settings — useful for dev override. |
| `RECRUITER_LOCAL_LLM_API_KEY` | Fallback key for a local OpenAI-compat endpoint. |
| `RECRUITER_DEV_AUTH_BYPASS` | Email that auto-logs-in without password. **Never set in production.** |
| `RECRUITER_OIDC_*` | Google OIDC sign-in (`ISSUER`, `CLIENT_ID`, `CLIENT_SECRET`, `REDIRECT_URI`). Empty issuer disables. |
| `RECRUITER_LOG_LEVEL` | Default `INFO`. |
| `SEARXNG_SECRET` | Secret key for the bundled SearXNG container. Generate via `openssl rand -hex 32`. Unset falls back to a placeholder — fine locally, do not ship to production. |

### Settings (UI tabs)

| Tab | What it holds |
|---|---|
| **LLM** | Provider (Anthropic / local) · provider key · base URL · model id (e.g. `openai/gpt-oss-120b:free` for LINAGORA, `claude-sonnet-4-6` for Anthropic) · monthly spend cap. |
| **Sourcing** | Search provider (SerpAPI / Google CSE / Brave / **SearXNG — bundled, no third-party key**) + key/URL · GitHub PAT · Apify token + actor slug · LinkedIn (cookie paste, or email+password with optional "Remember"). |
| **Enrichment** | Master toggle + per-source toggles (Twitter, YouTube, Stack Exchange) + API keys. |
| **Notifications** | SMTP host/port/user/password/from (encrypted). Required to send invite emails. Use port `587` with STARTTLS, not 25 (relay-only). |
| **Profile** | Recruiter name + email (used as the From: on outbound mail). |

### Search providers — quick comparison

| Provider | Cost | Setup | Per-call cap | Notes |
|---|---|---|---|---|
| **SearXNG** (bundled) | Free | None — comes up with `docker compose up -d` | ~30+ per call (paginated) | Aggregates Google, Bing, DuckDuckGo, Qwant, Startpage. No third-party account. |
| SerpAPI | Free tier ~100/mo (card required); paid from ~$50/mo | Sign up + key | ~10 (Google's quirk) | Best LinkedIn coverage; paid pagination for more. |
| Brave | Free tier 2,000/mo (card required) + paid | Sign up + key | 20 per call | Honors `count` directly. |
| Google CSE | 100/day free (requires GCP billing setup) | Sign up + key + engine id | 10 per call (hard cap) | OK but billing setup friction. |

Default after `docker compose up -d` is SearXNG. Switch in Settings → Sourcing → Search provider.

### LinkedIn extraction order

Each LinkedIn URL tries strategies until one works:

1. **Apify** (commercial scrape) — fastest. Needs token + actor slug.
   Tested actors: `supreme_coder/linkedin-profile-scraper` ($3/1k, free
   plan friendly), `dev_fusion/linkedin-profile-scraper` (best output,
   paid plan only).
2. **Playwright + stealth** — headless Chromium with your `li_at` cookie.
   Free but throttled by LinkedIn's anti-bot.
3. **GitHub-by-name fallback** — searches GitHub for the snippet name.
   Useful for engineers, useless otherwise.
4. **Manual paste** — after 90s of failed auto-extraction the UI prompts
   for a paste.

## Day-to-day flows

**Create a job** — `/jobs/new`. Paste a JD; the LLM proposes 3-6 weighted
criteria you can edit before creating the job.

**Add candidates** — on a job's kanban, click **Add candidate**:
- *URL* — LinkedIn / GitHub / personal site
- *Upload* — PDF or DOCX
- *Paste* — copy-paste profile text
- *Search* — pick LinkedIn / GitHub / Web, set the **Per source** count
  (1–30, default 5), optionally click the **Sparkles ✦** button to generate
  the query from the job description, then *Search* and click *Add* on a
  result.

**Score → Validate → Invite** — once the candidate is *Scored*, click
**Validate**. From the validated stage, click **Notify & invite** to open a
4-step wizard (channel → slots → LLM-drafted email → confirm) that sends an
SMTP invite with an ICS attachment and moves the candidate to *Invited*.

**Edit a candidate** — pencil icon next to the name opens an inline form for
name, email, phone, headline, location, summary. (Skills / experience /
education / links remain LLM-extracted, not editable.)

**Reject** — opens a dialog for a structured reason; visible as a banner on
the candidate detail page until you Unreject.

## Development

```bash
# Backend
uv sync && uv run pytest                     # tests
uv run alembic upgrade head                  # migrations

# Frontend
cd recruiter-frontend
npm install
npm run dev                                  # vite at :5173, proxies /api
npm test                                     # vitest (component)
npm run e2e                                  # playwright (full app)
```

The e2e suite assumes `docker compose up -d` is already running. Tests are
self-discovering — they pick any job/application that exists rather than
hard-coding IDs.

## Security notes

- All secrets in the DB are encrypted with Fernet under
  `RECRUITER_SETTINGS_KEY`. Back that key up.
- Session cookies are HttpOnly, SameSite=Strict, SHA-256-hashed at rest.
  Login is rate-limited (`5/minute`).
- A CSRF Origin allowlist gates every mutating endpoint; configure via
  `RECRUITER_ALLOWED_ORIGINS`.
- `RECRUITER_DEV_AUTH_BYPASS` is dev-only — never set in production.
- Uploaded CVs are stored under `var/resumes/`; the volume is gitignored.

## License

See `LICENSE`.
