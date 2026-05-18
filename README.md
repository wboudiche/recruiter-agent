# Recruiter Agent

An AI-assisted sourcing tool for individual recruiters and small teams. Paste a
LinkedIn URL, drop a CV, or search by job description — the system extracts a
structured candidate profile, enriches it from public web sources, and scores
it against your job's weighted criteria. Everything runs locally in Docker
against your own LLM, search, and (optional) commercial-scraping API keys.

---

## Table of contents

1. [What it does](#what-it-does)
2. [Quick start](#quick-start)
3. [Architecture](#architecture)
4. [The candidate pipeline](#the-candidate-pipeline)
5. [The recruiter agent](#the-recruiter-agent)
6. [Configuration reference](#configuration-reference)
7. [User guide](#user-guide)
8. [Operational notes](#operational-notes)
9. [Development](#development)

---

## What it does

You create a **Job** (title + description + weighted criteria). You add
**Candidates** to the job from any of these inputs:

- A LinkedIn URL
- A GitHub URL
- An arbitrary web page (personal site, blog, portfolio)
- A pasted profile (when scraping is blocked)
- An uploaded CV (`.pdf`, `.docx`)
- A search-and-add flow (LinkedIn / GitHub / Web search → click *Add* on a result)

For each candidate, the agent:

1. **Fetches** the underlying source.
2. **Extracts** name, headline, location, summary, experience, education, skills
   (LLM-driven structured output).
3. **Enriches** the profile with what it can find from links in the bio
   (blog, GitHub, portfolio, Stack Exchange, YouTube) and stores summaries
   per source.
4. **Scores** the candidate (0-100) against each criterion you defined, with
   a per-criterion rationale and a weighted overall score.
5. **Surfaces** the result on a kanban with stages
   `Extracting → Enriching → Scored → Validated → Invited → Scheduled → Rejected`.

A real-time SSE stream pushes stage transitions to the UI so the kanban moves
without manual refresh.

---

## Quick start

Requires Docker + an Anthropic API key (the only hard dependency for LLM
calls; a local OpenAI-compat endpoint also works).

```bash
git clone <repo> recruiter-agent
cd recruiter-agent

# minimum env — secrets cipher key + admin credentials
cp .env.example .env
# edit .env: RECRUITER_SECRETS_KEY=<32-byte base64>
#            RECRUITER_ADMIN_EMAIL=you@example.com
#            RECRUITER_ADMIN_PASSWORD=<long random string>

docker compose up -d --build
# UI:  http://localhost:8088
# API: http://localhost:8088/api
# Docs: http://localhost:8088/docs
```

Log in with the admin email + password from `.env`. Open **Settings → LLM** and
paste your Anthropic key. Everything else (search, GitHub, LinkedIn, Apify) is
optional — the system runs in increasingly capable modes as you configure more
keys.

---

## Architecture

### Stack at a glance

```
┌──────────────────────────────────────────────────────────────────┐
│                          Browser (React)                          │
│  React 18 · Vite · TanStack Query · React Hook Form · Tailwind   │
│  shadcn/ui · SSE subscription                                    │
└──────────────────────────────────────────────────────────────────┘
                                  │
                                  │  HTTPS · session cookie · SSE
                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│                           FastAPI (Python 3.12)                   │
│  ┌─────┐ ┌─────┐ ┌────────┐ ┌──────┐ ┌──────┐ ┌─────────────┐    │
│  │/jobs│ │/apps│ │/sourcing│ │/chat │ │/cands│ │/events (SSE)│    │
│  └──┬──┘ └──┬──┘ └────┬────┘ └──┬───┘ └──┬───┘ └──────┬──────┘    │
│     │       │         │         │         │            │           │
│  ┌──┴───────┴─────────┴────┐  ┌─┴─────────┴──────────┐ │           │
│  │  Pipeline orchestrator  │  │  Agent loop          │ │           │
│  │ fetch → extract → enrich│  │  LLM ↔ 11 tools      │ │           │
│  │ → score → persist       │  │  (read/search/action)│ │           │
│  └────────────┬────────────┘  └──────────┬───────────┘ │           │
│               │                          │             │           │
│               └────── emit stage / chat events ────────┘           │
└──────────────────────────────────────────────────────────────────┘
                                  │
        ┌─────────────────────────┼────────────────────────┐
        ▼                         ▼                        ▼
   ┌─────────┐              ┌──────────┐            ┌────────────┐
   │ Postgres│              │ LLM      │            │ Sources    │
   │ + JSONB │              │ Anthropic│            │ Apify      │
   │ Alembic │              │  -or-    │            │ Playwright │
   │         │              │ OpenAI   │            │ GitHub API │
   │         │              │ compat   │            │ SerpAPI etc│
   └─────────┘              └──────────┘            └────────────┘
```

### Backend layout (`src/recruiter/`)

| Path | Responsibility |
|---|---|
| `api/` | FastAPI routers — `jobs.py`, `candidates.py`, `applications.py`, `auth.py`, `chat.py`, `events.py`, `notifications.py`, `settings.py`, `sourcing.py` |
| `pipeline/` | Background processing — `orchestrator.py` drives `fetchers → extractor → enrichers → scorer` |
| `pipeline/fetchers/` | `github.py`, `linkedin_playwright.py`, `linkedin_stub.py`, `webpage.py` |
| `pipeline/enrichers/` | `linkedin_via_github.py`, `web.py` |
| `pipeline/parsers/` | `pdf.py`, `docx.py`, `text.py` |
| `sourcing/` | LinkedIn login + sourcing providers — `apify.py`, `linkedin_login.py`, `serpapi.py`, `google_cse.py`, `brave.py`, `searxng.py`, `github.py`, `search.py` |
| `models/` | SQLAlchemy ORM — `Job`, `Application`, `Candidate`, `SettingsRow`, `User`, `AuthSession`, `ChatMessage`, `EventLog`, `Notification` |
| `schemas/` | Pydantic models for API + structured-LLM-output validation |
| `llm/` | Provider clients — `anthropic.py`, `openai_compat.py`, `client.py` (interface + fake) |
| `auth/` | Local-password + OIDC (Google) — `local.py`, `oidc.py`, `session.py`, `password.py` |
| `enrichment/` | Per-source enrichers (GitHub, blog/web, Twitter, YouTube, Stack Exchange) + orchestrator |
| `agent/` | **Conversational tool-using agent** — `chat.py` (LLM loop), `tools.py` (11 registered tools), `events.py` (SSE event factories), `undo.py` (reversible action store), `types.py`. See [The recruiter agent](#the-recruiter-agent). |
| `notifications/` | In-app + email notifications |
| `events.py` | In-process pub/sub used by the SSE endpoint |
| `crypto.py` | Fernet helpers for secret-at-rest encryption |
| `config.py` | `pydantic-settings` — env-var driven runtime config |
| `db.py` | Engine factory + session dependency |
| `main.py` | FastAPI app assembly + middleware + lifespan |

### Frontend layout (`recruiter-frontend/src/`)

| Path | Responsibility |
|---|---|
| `routes/` | Top-level pages — `jobs-list`, `jobs-new`, `job-detail`, `application-detail`, `login`, `settings` |
| `components/kanban/` | `kanban-board`, `kanban-column`, `candidate-card`, `add-candidate-panel`, score badges |
| `components/candidate/` | `candidate-profile`, `enrichment-section`, `score-breakdown`, `action-bar` |
| `components/applications/` | `chat-panel`, `paste-profile-form`, `search-result-card` |
| `components/jobs/` | `edit-criteria-sheet` |
| `components/settings/` | `sourcing-tab`, `linkedin-connect`, plus LLM / Profile / Enrichment / Notifications tabs |
| `components/command-palette/` | ⌘K navigation |
| `components/ui/` | shadcn/ui primitives + `spinner` |
| `hooks/` | `use-jobs`, `use-job`, `use-job-applications`, `use-application`, `use-candidate`, `use-settings`, `use-chat`, `use-current-user`, `use-kanban-selection` |
| `lib/api.ts` | Fetch wrapper with 401 → `/login` redirect + `ApiError` |
| `lib/sse.ts` | SSE subscription → invalidates relevant React-Query keys on stage events |
| `lib/query-keys.ts` | Centralised React-Query key factories |
| `lib/time.ts` | Stage-relative timestamp + ageing colour |
| `styles/` | Tailwind config + the editorial dark theme (`geist-theme.css`, `globals.css`) |

### Database

PostgreSQL 16. Schema is managed by Alembic; recent migrations cover
encrypted-cookie storage, the Apify column, the configurable Apify actor,
and the auto-reconnect credentials.

Core tables: `users`, `auth_sessions`, `jobs`, `candidates`, `applications`,
`chat_messages`, `event_logs`, `notifications`, `settings` (singleton).

`applications.enrichment` is a JSONB blob keyed by source. `candidates.skills`,
`candidates.experience`, `candidates.education` are JSONB arrays.

---

## The candidate pipeline

### Stages

```
sourced ──► extracting ──► enriching ──► scored ──► validated ──► invited ──► scheduled
                                            │
                                            └────► rejected (from any stage)
```

`sourced` is reserved for bulk imports; today every candidate starts at
`extracting`.

### What runs at each stage

**Fetch (transition `extracting` is entered)**

| URL kind | Order tried | Notes |
|---|---|---|
| LinkedIn | 1. **Apify** (if API token + actor slug set) → 2. **Playwright with cookie** (if cookie set, with auto-reconnect via stored credentials if available) → 3. **GitHub-by-name enricher** (best-effort match) → 4. **Manual paste fallback** | Each path either returns rendered text or fails with `needs_paste=true` and a reason |
| GitHub | GitHub REST API direct (`/users/<login>` + `/users/<login>/repos`) | No auth required; PAT raises rate limit to 5k/hr |
| Other web | Trafilatura on the fetched HTML | Strips boilerplate, returns main content as text |
| Uploaded file | `.pdf` → pdfminer.six; `.docx` → python-docx | Text content fed to extractor |

**Extract**

Anthropic Claude (or your configured LLM) is prompted with the fetched text
plus a strict `ExtractedCandidate` Pydantic schema. Tool-use enforces
JSON-shape compliance.

**Enrich (transition `enriching`)**

`enrichment/` discovers links in the candidate's profile/summary (URLs, GitHub
handle hints, Stack Overflow IDs, YouTube channel mentions). Each enabled
source is fetched and summarised. Results are cached for **30 days**;
`Re-enrich now` on the detail page bypasses the cache.

Enrichment sources, toggleable in **Settings → Enrichment**:
`github`, `blog`, `web` (always on if enrichment enabled),
`stackexchange`, `youtube`, `twitter` (require API keys).

**Score**

The LLM scores each criterion from 0-10, returning:
- per-criterion score
- per-criterion rationale
- weighted overall score (0-100, computed server-side)
- prose rationale

**Stage transition**

The orchestrator commits the candidate, sets `applications.stage = scored`,
and emits a `stage` SSE event so the kanban updates without polling.

### Failure modes — what happens when

| Symptom | Cause | Fallback |
|---|---|---|
| Card stuck in **Extracting**, *"Extracting profile…"* badge | Pipeline running normally (< 90 s) | Wait |
| Card stuck in **Extracting**, *"Needs profile"* yellow badge | LinkedIn URL → all extraction paths failed; > 90 s elapsed | Open detail page, paste profile content manually |
| Score = 0, breakdown empty | Job has no criteria | Edit criteria on the job detail page |
| Experience / education empty, only skills populated | Apify actor returned partial data, or fell back to GitHub-by-name enricher (GitHub repo languages != LinkedIn skills) | Try a different Apify actor, or rotate LinkedIn cookie |
| All `start` dates `null` | The configured Apify actor doesn't emit dates | Swap to a different actor that does |
| 500 on Add | Almost always a fetcher bug — every known path returns a typed error rather than raising | Check `docker compose logs backend`, file an issue |

---

## The recruiter agent

The pipeline gets you a scored candidate; the **agent** is what lets you
*reason about* and *act on* candidates conversationally. It's the chat
panel on the right of every application detail page, but it's not a simple
LLM chatbot — it's a tool-using agent with bounded authority over the
application's state.

### Loop

```
User message ──┐
               ▼
        ┌──────────────────────────────────┐
        │ LLM ↔ tools  (Anthropic / local) │
        │  - read tools     (cheap)        │ ◄─── streams `message_delta`,
        │  - search tools   (LLM cost)     │      `tool_call_start`,
        │  - action tools   (mutating)     │      `tool_call_result`
        └──────────────────────────────────┘      back to the browser as
                                                  SSE events
                ▼
        Final assistant turn
        persisted as ChatMessage
```

The loop runs at most `MAX_STEPS_DEFAULT = 8` turns per user message —
enough for *"find me three similar profiles, save a note, and reject the
weakest one"* in a single interaction, but bounded so a confused model
can't loop forever. Each step is one tool call or the final answer.

### Tools the agent has

All 11 tools are defined in [`src/recruiter/agent/tools.py`](src/recruiter/agent/tools.py).
The handler dict + `ToolDef` list keep schemas and implementations together,
which the LLM provider's tool-use mechanism consumes directly.

**Read tools** (no side effects, called freely):

| Tool | Purpose |
|---|---|
| `get_candidate` | Full extracted profile — name, headline, location, skills[], experience[], education[], summary, links |
| `get_application` | Stage, score, score breakdown, notes, enrichment, awaiting_paste status |
| `get_score_breakdown` | Just the per-criterion scores + rationales, formatted for chat reasoning |
| `get_job` | Job title, description, criteria array — so the agent can reason about fit |
| `list_other_applications_for_candidate` | This candidate's stage in *other* jobs — prevents poaching across pipelines |

**Search tools** (LLM-driven, cost real money on every call):

| Tool | Purpose |
|---|---|
| `search_linkedin` | Same sourcing provider as the *Add candidate → Search* tab, scoped to LinkedIn |
| `search_github` | GitHub-by-keyword |
| `search_web` | Generic web search |

Results are returned as **structured candidate cards** (name + snippet +
URL), so the agent can refer to them by index and the UI can render an
*Add* button on each.

**Action tools** (mutating, reversible via the undo store):

| Tool | Purpose |
|---|---|
| `save_note` | Append a recruiter-private note to the application |
| `validate_application` | Promote stage `scored → validated` |
| `reject_application` | Promote any stage → `rejected` |

Every action goes through `agent/undo.py`, which stores the inverse
operation. The UI offers an **Undo** button on each rendered tool-call
result for as long as the inverse is valid (typically until the next
mutating action or page reload).

### What you can ask it

The chat sees the full candidate context plus the job criteria, so prompts
like these work without you supplying any state:

- *"How does Arunn compare to the criteria? Be specific about which
  evidence in his profile matches."*
- *"Find me three more candidates similar to this one but based in Europe."*
- *"Save a note that I'm waiting on a referral check, then reject him for
  now."*
- *"Has this person applied to any other roles?"*
- *"Draft three interview questions calibrated to his weakest criterion."*

The agent will read what it needs, call search tools where appropriate,
take actions if you authorise them, and return a final answer with the
reasoning visible inline as expanded tool-call panes.

### Why split the agent from the pipeline?

- **The pipeline runs once per candidate** and produces deterministic
  output (the score breakdown). It must work without LLM creativity.
- **The agent runs on demand**, reads what the pipeline produced, and
  helps the recruiter think + act. Different latency profile, different
  cost profile, different failure modes.

Both share the same LLM client, the same DB session, the same models.
Splitting the responsibility means scoring is reproducible and the chat
can evolve without destabilising the scoring step.

---

## Configuration reference

All configuration is either an **env var** (read at startup) or a **Settings
row** (encrypted at rest, editable via the UI). Settings always win over env
vars where both exist, **except** `RECRUITER_LINKEDIN_LI_AT` (env wins, useful
for dev override).

### Env vars (`.env`)

| Var | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | yes (set by docker-compose) | Async Postgres DSN |
| `RECRUITER_SECRETS_KEY` | **yes** | Base64-encoded 32-byte Fernet key used to encrypt every `*_enc` column. Lose this and your stored API keys become unrecoverable. |
| `RECRUITER_ADMIN_EMAIL` | yes (first run) | Seeds the initial admin user |
| `RECRUITER_ADMIN_PASSWORD` | yes (first run) | bcrypt-hashed on first start |
| `RECRUITER_SESSION_TTL_DAYS` | no | Login session lifetime, default `7` |
| `RECRUITER_LINKEDIN_LI_AT` | no | LinkedIn `li_at` cookie. If set, overrides whatever is stored in Settings. Mostly for dev. |
| `RECRUITER_DEV_BYPASS_AUTH` | no | Skip auth entirely. **Never enable in shared environments.** |
| `ANTHROPIC_API_KEY` | no | If set, used as the default LLM key (the Settings UI value takes precedence) |
| `RECRUITER_OIDC_*` | no | Google OIDC sign-in — `CLIENT_ID`, `CLIENT_SECRET`, `REDIRECT_URI` |

### Settings (UI: `/settings`)

**LLM tab**
- Provider: `anthropic` (default) or `local` (OpenAI-compat endpoint)
- Anthropic API key (encrypted)
- Local LLM URL + optional API key
- Model overrides (advanced — pin model per task)
- Monthly spend cap (USD, soft warning)

**Sourcing tab**
- **Search provider**: SerpAPI (default), Google CSE, Brave, SearXNG
- **Search API key** (encrypted), CSE engine ID, or SearXNG instance URL
- **GitHub PAT** (optional, raises GitHub API rate limit 60 → 5,000/hr)
- **Apify API token** (encrypted) — when set, LinkedIn URLs route through Apify first
- **Apify actor** — slug like `username/actor-name`. Default
  `dev_fusion/linkedin-profile-scraper`. See *LinkedIn extraction strategies* below.
- **LinkedIn auto-extraction** — Connect via credentials *or* paste-cookie modal

**Enrichment tab**
- Master toggle `enrichment_enabled`
- Per-source toggles (twitter, youtube, stackexchange)
- Per-source API keys (encrypted)

**Profile tab**
- Recruiter name + email (used as the From: on outbound mail)
- SMTP configuration (encrypted) — required for invite emails

**Notifications tab**
- In-app preferences

### LinkedIn extraction strategies

The pipeline tries strategies in this order, falling through on failure:

1. **Apify** (commercial scrape API) — fastest + most reliable when working.
   Requires an API token and an actor slug. Different actors have different
   pricing, output shapes, and plan-tier restrictions. The renderer in
   `apify.py` already handles the common variations.

   Currently tested actors:
   - `supreme_coder/linkedin-profile-scraper` ($3/1k, no LinkedIn cookies required, ~$5/month free credit). Doesn't emit dates.
   - `curious_coder/linkedin-profile-scraper` (your-cookies version, $4/1k).
   - `dev_fusion/linkedin-profile-scraper` (best output, paid Apify plan only for API).

2. **Playwright with stealth** — headless Chromium driving LinkedIn with your
   `li_at` cookie. Free but throttled by LinkedIn's anti-bot.
   The cookie is captured one of three ways via the *Connect LinkedIn* modal:
   - **Paste cookie** (open LinkedIn devtools → copy `li_at` cookie value)
   - **Email + password** (we drive the login flow once; password is consumed
     immediately and not persisted by default)
   - **Email + password + "Remember"** checkbox (password is persisted
     encrypted; auto-reconnect runs when the cookie is rejected by LinkedIn)

3. **GitHub-by-name enricher** — searches GitHub for the snippet name and
   uses the matched user's profile as the source. Useful for engineering
   roles when LinkedIn is blocked; useless for non-engineers.

4. **Manual paste** — the candidate detail page's right pane shows a
   textarea + a deep link to the LinkedIn profile. Open in your browser,
   Cmd-A / Cmd-C the page, paste, submit.

A LinkedIn URL fails over silently between strategies. Once `awaiting_paste`
is true on the application (after the 90-second auto-extraction grace
window), the UI prompts the user to paste.

---

## User guide

### 1. Create a job

`Jobs → New job`. Type a title and paste the job description. Click
**Suggest from JD** — the LLM proposes weighted criteria (typically 3-5
criteria summing to ~1.0). Tweak names, weights, descriptions; the criteria
sheet is also reachable later via the **Criteria** button on the job detail
page.

A job with no criteria scores every candidate 0/0. The system warns you
about this when scoring runs.

### 2. Add candidates

Click **Add candidate** on the job detail page. Four tabs:

- **URL** — paste a LinkedIn / GitHub / personal-site URL.
- **Upload** — drop a `.pdf` or `.docx` CV.
- **Paste** — paste profile text directly (skips the fetcher entirely).
- **Search** — query LinkedIn / GitHub / Web. Each result has an **Add**
  button. The search pre-fills the candidate's name and search snippet so
  even if scraping fails you have something to work with.

The card appears in the **Extracting** column with the amber *"Extracting
profile…"* badge and a live loader on the detail page. After 20-30 seconds
it moves to **Scored** with a numeric score (0-100).

### 3. Triage on the kanban

- Cards are stacked by score within each column (highest first).
- Score badge colour: red < 50, yellow 50-79, green ≥ 80.
- **Show rejected** toggles the rejected pile.
- **Comfortable / Compact** density swaps card layout.
- Click any card to open the detail page.

### 4. Review the detail page

Top: name, headline, photo (if available), location.

**Score breakdown** — per-criterion score 0-10, weight, rationale.
The job criteria are the *only* thing the scorer uses; if they don't match
what you actually care about, edit them on the job page.

**Enrichment** — discovered links per source (blog, GitHub, etc.) with the
LLM's per-source summary. Cached for 30 days; **Re-enrich now** bypasses
the cache.

**Agent chat** (right pane, only after extraction finishes) — the
conversational agent described in [The recruiter agent](#the-recruiter-agent).
It can read the full profile, search for similar candidates, save notes,
and validate / reject the application on your behalf — see that section
for the full tool list and example prompts.

### 5. Move the candidate forward

- **Validate** — promote to Validated (your shortlist).
- **Reject** — drop to Rejected.
- **Invite** (once configured: SMTP + a recruiter email signature) — drafts
  an email to the candidate using their extracted info; you review and send.
- **Schedule** (after invite) — once they reply with availability, you mark
  it scheduled.

Stage transitions emit SSE events; the kanban updates without refresh on
every connected tab.

### 6. (Optional) Re-extract a stuck candidate

If a card is stuck in `extracting` with the *Needs profile* badge:

1. Open the LinkedIn URL in your normal browser.
2. Select-all / copy.
3. Paste into the textarea on the detail page → **Submit**.
4. The candidate re-enters the pipeline as if it were a `Paste`-tab add.

Or just **Reject** and re-add — useful when you've since configured Apify
or rotated the LinkedIn cookie.

---

## Operational notes

### Storage costs

The Apify path costs ~$0.01-0.05 per LinkedIn profile depending on actor +
plan. Playwright is free but uses your LinkedIn account's reputation
budget. Enrichment hits external sites at most once per profile then caches
for 30 days. LLM cost is dominated by the score step; long candidate
profiles cost more.

### Secrets

Every `*_enc` column (Anthropic key, search API key, GitHub PAT, Apify
token, LinkedIn cookie, LinkedIn password if Remember, SMTP password,
Google OAuth tokens) is Fernet-encrypted with `RECRUITER_SECRETS_KEY`.

If that env var is missing on next startup, the data is intact in the
database but the app can't decrypt it. **Back up the key.**

### LinkedIn anti-bot

After 50-100 profile fetches per LinkedIn cookie session, LinkedIn starts
serving the *"Limited public profile"* view or, with heavier use, redirect-
loops the URL entirely. Rotation (paste a fresh `li_at`) or auto-reconnect
generally restores access. The Apify path bypasses this risk by using their
infrastructure.

The system gracefully degrades when LinkedIn fights back: redirect loops
and timeouts are caught as `ApifyError` / `PlaywrightError`, surface as
`needs_paste=True` with a clear `reason`, and the candidate falls through
to manual paste rather than crashing.

### Authentication

Local email + password (bcrypt) and Google OIDC. Sessions are stored as
SHA-256 hashes in `auth_sessions`. The session cookie is `HttpOnly`,
`SameSite=Lax`, `Secure` in HTTPS deployments.

CSRF protection: an Origin/Referer check rejects POST/PATCH/DELETE
requests from unexpected origins.

### Backup

```bash
# database
docker exec recruiter-agent-postgres-1 pg_dump -U recruiter recruiter > backup.sql

# secrets key — KEEP THIS
grep RECRUITER_SECRETS_KEY .env
```

---

## Development

### Running tests

```bash
# backend
uv run pytest tests/

# frontend
cd recruiter-frontend && npx vitest run
```

Backend tests use an ephemeral Postgres + dependency overrides for the LLM
(via `FakeLLMClient`) and the Playwright / Apify fetchers (via monkeypatched
stubs). Most paths are tested end-to-end at the HTTP layer.

### Hot-reload (without Docker)

```bash
# backend
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn recruiter.main:app --reload

# frontend
cd recruiter-frontend
npm install
npm run dev  # http://localhost:5173, proxied to :8000
```

### Adding a new search provider

Implement `SearchProvider` in `src/recruiter/sourcing/provider.py`, register
in `search.py`, add a UI option in `recruiter-frontend/src/components/settings/sourcing-tab.tsx`,
update the `Provider` literal in both `schemas/settings.py` and
the React hook.

### Adding a new Apify actor

Most actors work via the configurable slug — no code change. If the actor
uses unfamiliar JSON keys, extend the key-probe arrays in
`src/recruiter/sourcing/apify.py::_render_profile_text`. The renderer already
handles bare strings, `{name, text, title, value, label}` objects, and the
`{year, month}` date variant.

### Migrations

```bash
uv run alembic revision --autogenerate -m "describe change"
# edit the generated file under alembic/versions/
uv run alembic upgrade head
```

### Project conventions

- Async-everywhere on the backend (SQLAlchemy 2.x async, FastAPI async
  handlers, `httpx.AsyncClient`).
- Pydantic v2 for all API schemas and structured-LLM outputs.
- shadcn/ui + Tailwind on the frontend; no design-system imports from
  outside the repo.
- One responsibility per `api/` module; orchestration lives in `pipeline/`.

---

## License

Internal / proprietary unless otherwise noted in the repo.
