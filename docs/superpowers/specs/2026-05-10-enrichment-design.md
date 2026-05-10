# Candidate enrichment for scoring — Design

**Date:** 2026-05-10
**Status:** Draft

## Problem

Today's scoring pipeline (`src/recruiter/pipeline/scorer.py`) only sees what was extracted from the uploaded resume — skills, experience, education, links, summary. The LLM does not browse, search, or fetch anything during scoring. Strong public technical signals (GitHub commits, Stack Overflow answers, talks, blog posts) and public social presence are invisible to the score.

Users want the scorer to consider these signals, both from URLs the candidate explicitly listed and from public profiles discovered by name+employer search.

## Goal

Add an **enrichment pipeline stage** between extract and score that:

1. Fetches public profile content from a configurable set of sources.
2. Pre-discovers profiles by name+employer search (opt-in per job).
3. Scores identity-match confidence on each finding.
4. Persists results on the application.
5. **Surfaces the findings to the recruiter on the candidate detail page** as research material — never as input to the LLM scorer.

Enrichment is a **research aid for the recruiter**, not a scoring input. The score is computed from the resume only, exactly as today. The recruiter reviews the enrichment evidence themselves and uses it to make their own judgment about a candidate alongside the LLM score.

## Non-goals

- Modifying the LLM scorer. `pipeline/scorer.py` is unchanged. The score is computed from the resume only, identical to today's behavior.
- Replacing the resume-text-driven scorer. Enrichment runs alongside; missing/failed enrichment is non-fatal and scoring proceeds normally.
- Real-time enrichment in the chat agent. The chat agent already has its own sourcing tools (`agent/tools.py`); this work is about the candidate-detail page only.
- Personality / tone / culture-fit scoring from social posts. Since enrichment never reaches the LLM, this isn't even a possibility — by construction the recruiter is the only consumer of the social findings.
- LinkedIn deep enrichment (connections, endorsements, posts, recommendations). Microsoft has sued multiple companies for scraping LinkedIn. We use only the public-page snippet via the active sourcing provider, and rely on the resume parser's existing extraction of headline/summary.
- Image/video content analysis (Instagram, TikTok, Facebook). Closed APIs and very high bias risk for hiring use cases.
- Re-enrichment on every score retry. We persist results with a 30-day TTL; retries within TTL reuse the cached enrichment.

## Architecture

A new `src/recruiter/enrichment/` package mirrors the structure of `src/recruiter/sourcing/`. Each source is a pluggable provider registered via decorator.

```
src/recruiter/enrichment/
├── provider.py        # registry + EnrichmentProvider Protocol + result schemas
├── github.py          # public REST + GraphQL
├── stackoverflow.py   # Stack Exchange API (free, 300/day per IP)
├── hackernews.py      # Algolia search API (no key)
├── reddit.py          # /u/<name>.json public endpoint (no key)
├── mastodon.py        # public statuses API
├── bluesky.py         # AT proto public endpoints
├── youtube.py         # Data API v3 (free 10k units/day quota)
├── twitter.py         # X API v2 Basic tier ($200/month)
├── devto.py           # public REST
├── blog.py            # generic page fetch + LLM summarize
├── discovery.py       # uses active sourcing provider to find profiles
├── identity.py        # confidence scoring across providers
├── pipeline.py        # orchestrates discovery → enrich → consolidate
└── __init__.py        # imports each provider so @register fires
```

Each provider exposes:

```python
class EnrichmentProvider(Protocol):
    name: str
    domains: list[str]    # e.g., ["mastodon.social", "fosstodon.org", ...]

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None: ...
```

`EnrichmentHint` is the input shape: a URL (when known explicitly) or a name+employer pair (for discovery results). The provider is responsible for fetching the relevant public data, summarizing it into signals, and emitting an `EnrichmentResult`.

## Data contracts

```python
class EnrichmentSignal(BaseModel):
    type: Literal["code", "answer", "post", "talk", "writing", "profile"]
    summary: str            # one-line evidence the LLM can read
    url: str | None = None
    timestamp: datetime | None = None

class EnrichmentResult(BaseModel):
    source: str             # "github" | "stackoverflow" | "twitter" | ...
    profile_url: str
    confidence: float       # 0.0–1.0; only ≥0.7 reaches the score prompt
    discovered: bool        # True if found via discovery, False if from candidate.links
    signals: list[EnrichmentSignal]
    summary: str            # one-paragraph overview the LLM consumes

class EnrichmentBundle(BaseModel):
    fetched_at: datetime
    expires_at: datetime    # fetched_at + 30d
    discovery_consent: bool # whether discovery was authorized for this run
    results: list[EnrichmentResult]
    errors: list[dict]      # { source, error, transient } for observability
```

## Identity matching

Confidence is assigned per result and gates how the result is presented to the recruiter on the candidate detail page. Since enrichment never reaches the score, the worst-case from a wrong identity match is "the recruiter sees a stranger's posts on this candidate's page" — bad UX, but not bad scoring. Confidence still matters because misattributed posts mislead the recruiter; we just don't have to be paranoid about it the way a scoring input would require.

### Confidence tiers

| Confidence | Source                                                                                            | Recruiter UI                |
|------------|---------------------------------------------------------------------------------------------------|-----------------------------|
| 1.0        | URL listed in `candidate.links` (resume / LinkedIn export). Fetch directly.                       | shown prominently           |
| 0.8        | Username derived from a 1.0 match (e.g., GitHub handle `alice123` → try `stackoverflow.com/u/alice123`). Confirmed by at least one cross-link, matching email domain, or matching real name. | shown prominently           |
| 0.5        | Discovered via name+employer search, no other corroboration.                                      | shown with "low confidence" badge in collapsed section |
| 0.75       | Discovered via name+employer, corroborated by ≥2 independent sources (cross-links match).         | shown prominently           |
| <0.5       | Weak match (name only, single source).                                                            | discarded                   |

### Cross-corroboration rules

- A profile that explicitly links to another already-confirmed profile (e.g., a Mastodon bio linking to GitHub which is at 1.0) inherits 0.8 confidence.
- A profile whose username exactly matches a confirmed-profile username on another platform earns +0.2 (capped at 0.8).
- A profile whose email/website on the public page matches the candidate's email or a 1.0 link earns +0.3.

### Identity engine

`enrichment/identity.py` runs after all providers report results. It builds a graph of cross-references and propagates confidence. Persisted alongside the results in `EnrichmentBundle.results[*].confidence`.

## Discovery layer

Opt-in per job via a consent checkbox (see Settings / consent). When enabled:

1. For each enrichment provider with `domains` set, the discovery layer issues `"<full_name>" "<current_employer>" site:<domain>` queries via the **active sourcing provider** (Brave / SerpAPI / Google CSE / SearXNG, whatever the user configured).
2. Top result per `(provider, domain)` becomes an enrichment hint at confidence 0.5.
3. Each hint is then enriched by its respective provider, which can raise confidence via cross-corroboration.

Costs and behavior:
- 8–15 sourcing API calls per candidate (one per `(provider, domain)` pair).
- Adds ~3–5 s latency before the enrichment fetch step.
- On a free Brave key (2000/month), this caps total enrichment-driven sourcing at ~150 candidates/month before quota concerns. With SerpAPI free (100/month) it's ~7. Discovery is most useful for users on SearXNG (unlimited) or paid sourcing tiers.
- Discovery off → only `candidate.links` URLs are enriched. Zero discovery cost. Lower coverage.

## Score prompt — unchanged

`pipeline/scorer.py` is **not modified**. The LLM continues to score using only the job description, criteria, and structured candidate data extracted from the resume. The score the recruiter sees in the kanban is the same number it would be without enrichment.

This was a conscious product decision (Decision 1 → Option C, "no score impact, surface for human review only"): enrichment is a research aid for the recruiter, not an input to automated scoring. Removing the LLM from the social-content path eliminates an entire class of bias-amplification and personality-inference risks.

## Settings and consent

### Two flags

1. **Global kill switch** (env var): `RECRUITER_ENABLE_ENRICHMENT=true|false`. Default `false`. When `false`, the enrichment stage no-ops for all jobs and no API calls are made.

2. **Per-job consent** (Job model column): `enrichment_consent: bool`. Default `false`. The recruiter ticks a checkbox on the job-create / job-edit form asserting they have lawful basis for processing the candidate's public technical and social presence for hiring decisions.

The `enrichment_consent` flag controls **both** Twitter/X usage and discovery searches. When `false`:
- Only candidate-listed URLs are enriched.
- No discovery searches run.
- No Twitter/X calls (Twitter is the highest-bias / highest-cost source; we tie it to consent).

When `true`:
- Discovery searches run.
- All providers including Twitter/X are eligible.

### Provider keys

Twitter/X requires a key. Settings UI gains:
- `enrichment_twitter_api_key_enc` (encrypted)
- Help text: "X API Basic tier required (~$200/month)"

YouTube Data API v3 needs a Google API key (10k units/day free). Settings UI gains:
- `enrichment_youtube_api_key_enc` (encrypted)

GitHub already has a token field on the existing Sourcing tab (`github_token_enc`). Reused — no new field.

Stack Overflow's Stack Exchange API works without a key for low volume (300 req/IP/day) but has higher quota with a key. Optional:
- `enrichment_stackexchange_key_enc` (encrypted, optional)

## Pipeline integration

`Stage` enum gains `ENRICHING` between `EXTRACTING` and `SCORED`. Order:

```
QUEUED → EXTRACTING → ENRICHING → SCORED
```

`process_application` in `pipeline/orchestrator.py`:

1. After successful extract, if `enrichment_enabled and job.enrichment_consent and not bundle_within_ttl`:
   1. Publish `Stage.ENRICHING` to the event bus.
   2. Call `enrichment.pipeline.enrich(candidate, job)`.
   3. Persist `application.enrichment` JSON column.
   4. Log `application.enriched` event with summary stats (sources hit, errors, total signals).
2. If enrichment fails, log `enrichment.failed` event. Scoring proceeds normally.
3. If enrichment is skipped (kill switch / no consent / cached bundle within TTL), nothing happens — scoring proceeds normally.
4. **`score_candidate` is called with the same arguments as today.** Enrichment results are NOT passed into scoring.

Why run enrichment as a pipeline stage (rather than on-demand from the candidate page)? Two reasons:
1. The recruiter sees enrichment evidence as soon as they open the page, no clicking-and-waiting.
2. The 30-day TTL only works if there's a deterministic point at which enrichment runs. The pipeline stage is that point.

## Persistence

New `Application.enrichment` JSON column. Schema = `EnrichmentBundle`.

- TTL: 30 days. Within TTL, retries and the candidate-detail page reuse the cached bundle.
- After TTL: re-enrichment runs on next pipeline pass.
- **Manual "re-enrich" button** (per Decision 3): zeros out the column and triggers a fresh enrichment pass. Implemented as a `POST /api/applications/{id}/re-enrich` endpoint that clears the column and republishes the application to the pipeline at `Stage.ENRICHING`.

Migration: single Alembic revision adding the JSON column with default `null`.

## Source-by-source approach

| Source              | API                                         | Auth                | Quota                     | Domains                                            |
|---------------------|---------------------------------------------|---------------------|---------------------------|----------------------------------------------------|
| GitHub              | REST `/users/{u}` + GraphQL contributions   | bearer (existing)   | 5000/h authed             | github.com                                         |
| Stack Overflow      | api.stackexchange.com                       | optional key        | 300/d unauthed, 10k authed| stackoverflow.com, stackexchange.com               |
| Hacker News         | hn.algolia.com/api                          | none                | unrestricted              | news.ycombinator.com                               |
| Reddit              | reddit.com/user/{u}/about.json + comments  | none                | 60/min unauthed           | reddit.com, old.reddit.com                          |
| Mastodon            | `/api/v1/accounts/lookup` + statuses        | none                | 300/5min                  | mastodon.social, fosstodon.org, hachyderm.io, …    |
| Bluesky             | `getProfile` + `getAuthorFeed`              | none                | unrestricted              | bsky.app                                           |
| YouTube             | Data API v3 search.list                     | API key             | 10k units/day             | youtube.com                                        |
| Twitter/X           | API v2 Basic tier                           | bearer              | 10k posts/month read      | twitter.com, x.com                                 |
| Dev.to              | dev.to/api                                  | none                | unrestricted              | dev.to                                             |
| Blog/website        | direct fetch + LLM summarize                | none                | bounded by candidate.links| any (candidate-listed only)                        |

For each provider:
- Mocked-transport unit tests cover happy path, empty results, auth errors, rate limit, network errors, identity match.
- Provider summarizes findings into 3–5 `EnrichmentSignal` items max (avoid prompt bloat).
- Each provider's `domains` list feeds the discovery layer (which sites it knows how to handle).

## Frontend changes

Two surfaces:

### Settings → Enrichment (new tab)

Mirrors the Sourcing tab's pattern. **Per-source toggles are core in v1** (per Decision 2).

- Master toggle: "Enable enrichment" (mapped to `RECRUITER_ENABLE_ENRICHMENT`-equivalent setting).
- Twitter/X API key (password input, masked when set).
- YouTube API key (optional).
- Stack Exchange key (optional).
- **Per-source enable/disable checkboxes** for all 10 sources. Disabled sources skip enrichment AND discovery searches for that domain. Default: all enabled.
- Help text and links to each provider's signup page.

### Job form → Consent checkbox

`enrichment_consent` on Job. Checkbox label:

> Process the candidate's public technical and social presence for scoring.
> Required where applicable law (e.g., GDPR Art. 6 + 9) demands lawful basis.

Default unchecked. Persists via the existing job CRUD endpoints (`schemas/job.py` gains the field).

### Application detail page

New "Enrichment" section. **Core deliverable in v1** (per Decision 4).

- Two-panel layout: high-confidence findings (≥0.75) prominently at the top, low-confidence (0.5) collapsed below behind a "Show 3 unconfirmed matches" toggle.
- Per result: source icon, profile URL (linked, opens in new tab), per-signal cards (timestamp, type, one-line summary, deep link).
- "Discovered" badge for results that came from name+employer search.
- "Confidence: 1.0 / 0.8 / 0.75 / 0.5" badge with hover-tooltip explaining what that means.
- "Cached: 12 days ago, expires 2026-06-09" indicator next to the section title.
- **"Re-enrich now" button** (per Decision 3) — clears the cache and reruns enrichment fresh. Disabled while enrichment is in progress; shows a spinner with the active stage.
- "Per-source error" details: if a source failed (e.g., Twitter quota exhausted), show a compact row with the error so the recruiter knows enrichment isn't complete.

## Testing

Mirrors the sourcing-providers test pattern.

- **Per-provider unit tests** (10–12 each, ~120 total). Mocked `httpx.AsyncClient` transport. Cover: 200 happy path, empty results, missing key field in response, 401, 429, 5xx, network failure, summary generation, signal cap.
- **Identity engine tests** (15–20). Cross-link propagation, threshold gating, name-collision handling.
- **Discovery layer tests** (8–10). Verify queries are well-formed, restricted to known domains, downstream provider hints have correct shape.
- **Pipeline integration tests** (5–8). Verify orchestrator skips enrichment when consent off, caches within TTL, re-runs after TTL, falls through gracefully on enrichment failure.
- **Score isolation tests** (2–3). Verify `score_candidate` is called with the same arguments whether enrichment ran or not, and that the score is identical with/without enrichment for the same resume.
- **Frontend tests** (12–15). Settings tab field visibility + per-source toggles, consent checkbox persistence, application-detail enrichment rendering (high vs low confidence sections, expand-collapse, re-enrich button, error display).

Pre-existing tests must remain passing.

## Rollout

Six commits, TDD red-green per provider. Order:

1. Foundation: `enrichment/provider.py` (Protocol, schemas, registry, identity engine), Alembic migration, `Stage.ENRICHING`.
2. GitHub provider (refactor: existing `sourcing/github.py` is a search-engine, not enrichment; we add a separate `enrichment/github.py` for the per-user enrichment shape).
3. Stack Overflow + Hacker News + Dev.to (all keyless or simple).
4. Reddit + Mastodon + Bluesky (free social).
5. YouTube + Twitter/X + blog/website (paid / generic — final paid integrations).
6. Discovery layer + pipeline orchestration + frontend.

Spec doc → plan doc (per-task code) → subagent-driven execution, same workflow as the sourcing providers.

Estimate: roughly 2× the sourcing-providers work. ~25 commits total. Full test suite stays green throughout.

## Decisions taken

1. **Score impact** → **C: no impact**. Enrichment never reaches the LLM scorer. The score is computed from the resume only, identical to today.
2. **Per-source toggles in Settings** → **yes, in v1**.
3. **Re-enrich button on candidate page** → **yes, in v1**.
4. **Enrichment data visible on candidate detail page** → **yes, in v1**.

## Remaining open questions

1. **Cost monitoring for Twitter/X** — $200/month for 10k posts/month read. A usage indicator in Settings would help avoid quota surprises. Deferred to v2 unless flagged.
2. ~~**What does the candidate detail page look like today?**~~ **Confirmed.** Page is `recruiter-frontend/src/routes/application-detail.tsx`, a 2-column layout. Enrichment section drops in below `<ScoreBreakdown />` in the left column.

## Risks

| Risk | Mitigation |
|------|------------|
| Identity matching false positives → recruiter sees a stranger's posts on a candidate's page | Confidence tiers visible in UI. Low-confidence results in a collapsed "unconfirmed matches" section. Recruiter can spot misattribution. Note: since enrichment never reaches the LLM, this can never affect the score. |
| Bias from social content | Eliminated by design: enrichment is recruiter-facing only. The LLM scorer is unaware of social findings. The recruiter retains all judgment about how (or whether) to weight social evidence. |
| Legal exposure (GDPR / regional hiring law) | Per-job `enrichment_consent` checkbox, global kill switch, default off. Documented in setup.md. Reduced exposure: the data is shown to humans for evidence review, not used for automated decision-making. |
| Twitter/X cost surprise | Tied to consent flag (no consent → no Twitter calls). Settings UI shows the $200/month line in help text. Cost-monitoring indicator deferred to v2. |
| Sourcing-provider quota exhaustion from discovery | Discovery is opt-in per job. With SerpAPI free (100/month), ~7 discovery-enabled candidates/month. Documented. |
| Enrichment failure blocks scoring | Cannot happen: enrichment runs in parallel/before scoring, but `score_candidate` is invoked the same way regardless. Enrichment failure logs `enrichment.failed` and the score still computes. |
| Stale enrichment data | 30-day TTL. Manual "Re-enrich now" button on the candidate page (v1) lets the recruiter refresh on demand. |
| Microsoft sues over LinkedIn scraping | We don't scrape. Use only the public-page snippet via the sourcing provider, plus what the resume parser already extracted. |
| YouTube quota exhaustion | 10k units/day, ~100 candidates/day. Cached for 30 days. Realistic ceiling. |
| Mastodon instance blocking us | Each mastodon.* domain is independent; failure on one instance doesn't affect another. Logged per instance. |
