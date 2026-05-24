# Changelog

All notable user-facing changes are recorded here. The format is loosely based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
follows semantic versioning post-1.0.

## v0.1.0-alpha — 2026-05-24

First public preview. Single-tenant, self-hosted recruiter assistant: add a
candidate from a URL, CV, paste, or search, and the system extracts a
structured profile, enriches it from public sources, scores it against your
job's weighted criteria, and lets you invite the candidate by email with a
calendar attachment.

### Added

- **Job + criteria.** Create jobs with title, description, and 3–6 weighted
  criteria. The LLM proposes initial criteria from the JD; weights can be
  edited freely and are normalized to sum to 1.0.
- **Candidate sources.** LinkedIn URL · GitHub URL · arbitrary web page ·
  paste · PDF/DOCX upload · search-and-add across LinkedIn / GitHub / Web.
- **LinkedIn extraction tiers.** Apify (commercial scrape) → Playwright with
  a stored `li_at` cookie → GitHub-by-name fallback → manual paste prompt.
- **Pipeline.** Async orchestrator runs `fetch → extract → enrich → score`
  with SSE-pushed stage updates to the kanban.
- **Scoring.** LLM-driven per-criterion score (0–100) with a one-sentence
  rationale and a weighted overall.
- **Validate → Notify wizard.** Four-step flow (channel → slots → LLM-drafted
  email → confirm) that sends an SMTP invite with an ICS attachment and
  moves the candidate to *Invited*.
- **Candidate editing.** Inline edit form for `full_name`, `email`, `phone`,
  `headline`, `location`, `summary` (the rest stay LLM-extracted).
- **Search-query suggester.** "Suggest from JD" button in the Search tab
  generates a source-aware query (LinkedIn-style keywords / GitHub
  `language:` filters / quoted Web Boolean) from the job description.
- **Conversational agent.** 11 registered tools, reachable from the Chat
  panel on every candidate detail page. Reversible actions go through an
  undo store.
- **Settings.** LLM (provider, key, model id, monthly spend cap) · Sourcing
  (search provider + key, GitHub PAT, Apify token + actor, LinkedIn cookie
  or credentials) · Enrichment (Twitter, YouTube, Stack Exchange) ·
  Notifications (SMTP host/port/user/password/from) · Profile (recruiter
  name + email).
- **Structured rejection.** Reject dialog captures a reason; banner on the
  detail page until the candidate is Unrejected.
- **Eager-seed bootstrap.** First start with `RECRUITER_DEFAULT_ACCOUNT_*`
  set creates the admin row before serving requests.
- **e2e tests.** Playwright suite (auth · candidate edit · search-query
  suggester) under `recruiter-frontend/e2e/` runnable via `npm run e2e`.
- **CI.** GitHub Actions runs backend pytest (testcontainers postgres) and
  frontend vitest + typecheck on every push and PR.

### Security

- All secrets in the DB (LLM keys, search keys, GitHub PAT, Apify token,
  LinkedIn cookie + password, SMTP password, OAuth tokens) are encrypted
  with Fernet under `RECRUITER_SETTINGS_KEY`.
- Session cookies are HttpOnly, SameSite=Strict, SHA-256-hashed at rest;
  login is rate-limited (`5/minute`).
- Compose refuses to start when required secrets are missing — no weak
  fallback can ship.
- CSRF Origin allowlist gates every mutating endpoint, configurable via
  `RECRUITER_ALLOWED_ORIGINS`.

### Known limitations

- **Skills / experience / education / links are LLM-extracted only** — not
  editable in the UI yet. Edit via SQL or re-paste the source if extraction
  got it wrong.
- **Gmail + Google Calendar channel is not wired** — only SMTP is functional;
  the Gmail option is hidden from the Notify wizard.
- **SerpAPI is the default search provider** but requires an API key. Brave
  and SearXNG are supported alternatives.
- **Playwright e2e is not yet in CI** — runs locally against `docker compose
  up -d`. CI runs backend pytest + frontend vitest + typecheck only.
- **No upgrade story** between releases yet — schema migrations work, but
  there is no formal pre-upgrade backup procedure documented beyond
  "back up `RECRUITER_SETTINGS_KEY` and the postgres volume."

### Recently fixed (since the previous unstable HEAD)

- `PATCH /api/candidates/{id}` no longer crashes with `MissingGreenlet` when
  the candidate row had a non-null `updated_at`.
- SMTP settings form now pre-fills host/port/user/from on open and keeps the
  stored password on partial updates instead of silently overwriting it
  with an empty string.
- LinkedIn-URL applications stuck waiting on manual paste now surface an
  explicit "needs paste" banner instead of an indefinite "extracting" label.
- LLM gateway errors propagate the upstream response body (e.g. LINAGORA's
  *"Model not found"*) instead of just the HTTP status.
- LLM tab exposes a per-provider Model input.
- README rewritten and shortened (~215 lines, down from ~666).
- First-run admin user is eager-seeded at backend startup rather than lazily
  on first successful login.
