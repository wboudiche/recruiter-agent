# Candidate enrichment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a per-candidate enrichment pipeline that fetches public profile content from 10 sources (GitHub, Stack Overflow, Hacker News, Reddit, Mastodon, Bluesky, Dev.to, YouTube, Twitter/X, blog/website), assigns identity-match confidence to each result, and surfaces the findings to the recruiter on the candidate detail page. Enrichment is a research aid: **`score_candidate` is invoked with the same arguments as today**, and the score is identical with/without enrichment for the same resume (per Decision 1 in the spec).

**Architecture:** A new `src/recruiter/enrichment/` package mirrors `src/recruiter/sourcing/`. Each provider registers via an `@register("name")` decorator and implements an `EnrichmentProvider` Protocol. A discovery layer reuses the active sourcing provider (`recruiter.sourcing.provider.resolve(settings)`) to find candidate profiles by name+employer search. A confidence engine (`enrichment/identity.py`) propagates cross-corroboration. The orchestrator inserts a `Stage.ENRICHING` step gated by a global kill-switch (`enrichment_enabled` setting) and a per-job `enrichment_consent` checkbox. Persisted as JSON on `Application.enrichment` with a 30-day TTL.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.x async, Alembic, httpx (with `MockTransport` for tests), pytest-asyncio. React 18, vitest, MSW, @testing-library/react, sonner toasts.

**Spec:** `docs/superpowers/specs/2026-05-10-enrichment-design.md`

**Reference plan:** `docs/superpowers/plans/2026-05-10-brave-searxng-providers.md` — the per-provider TDD cadence (failing test → impl → commit) and the `_make_provider` / `httpx.MockTransport` test pattern are identical here. Provider modules below reference that plan rather than duplicating boilerplate; only response-mapping logic and provider-specific test cases appear in full.

---

## Task list

| # | Task | Type |
|---|---|---|
| T1 | Migration + model fields + `Stage.ENRICHING` + `ApplicationRead.enrichment` | foundation |
| T2 | `enrichment/provider.py` — Protocol, schemas, registry | foundation |
| T3 | `enrichment/identity.py` — confidence engine | foundation |
| T4 | Hacker News — failing tests | provider (red) |
| T5 | Hacker News — implementation | provider (green) |
| T6 | Reddit — failing tests | provider (red) |
| T7 | Reddit — implementation | provider (green) |
| T8 | Mastodon — failing tests | provider (red) |
| T9 | Mastodon — implementation | provider (green) |
| T10 | Bluesky — failing tests | provider (red) |
| T11 | Bluesky — implementation | provider (green) |
| T12 | Dev.to — failing tests | provider (red) |
| T13 | Dev.to — implementation | provider (green) |
| T14 | Stack Overflow — failing tests | provider (red) |
| T15 | Stack Overflow — implementation | provider (green) |
| T16 | GitHub enrichment — failing tests | provider (red) |
| T17 | GitHub enrichment — implementation | provider (green) |
| T18 | YouTube — failing tests | provider (red) |
| T19 | YouTube — implementation | provider (green) |
| T20 | Twitter/X — failing tests | provider (red) |
| T21 | Twitter/X — implementation | provider (green) |
| T22 | Blog/website — failing tests | provider (red) |
| T23 | Blog/website — implementation | provider (green) |
| T24 | Discovery layer | pipeline |
| T25 | Pipeline (top-level enrich orchestrator) | pipeline |
| T26 | Orchestrator integration (`Stage.ENRICHING`) + score-isolation test | pipeline |
| T27 | API: `POST /applications/{id}/re-enrich` + settings/job schema fields | api |
| T28 | Settings → Enrichment tab (frontend, tests + impl combined) | frontend |
| T29 | Job form — consent checkbox | frontend |
| T30 | Application detail — `<EnrichmentSection />` + re-enrich button | frontend |
| T31 | Documentation | docs |
| T32 | Final verification | wrap-up |

---

### Task 1: Migration + model fields + `Stage.ENRICHING`

**Files:**
- Create: `alembic/versions/<auto>_add_enrichment_columns.py`
- Modify: `src/recruiter/models/application.py`
- Modify: `src/recruiter/models/job.py`
- Modify: `src/recruiter/schemas/application.py`
- Modify: `src/recruiter/schemas/job.py`
- Create: `tests/unit/test_enrichment_models.py`

**Why first:** Every later task touches one of these surfaces. The migration must land before any provider code can persist results.

- [ ] **Step 1: Generate the Alembic revision**

```bash
uv run alembic revision -m "add enrichment columns"
```

Replace the body of the new revision file with:

```python
"""add enrichment columns

Revision ID: <auto>
Revises: 4354790745ac
Create Date: 2026-05-10 ...

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "<auto>"
down_revision: Union[str, None] = "4354790745ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # JSON column on applications, default NULL — bundle is absent until
    # the enrichment pipeline stage has populated it.
    op.add_column(
        "applications",
        sa.Column("enrichment", sa.JSON(), nullable=True),
    )
    # Per-job consent flag, default False (opt-in per Decision per spec).
    op.add_column(
        "jobs",
        sa.Column(
            "enrichment_consent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Add ENRICHING to the `stage` enum. Postgres-only ALTER TYPE.
    # SQLite tests treat the enum as a free-text string so this is a no-op
    # there; the model-level enum gains the value automatically.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE stage ADD VALUE IF NOT EXISTS 'enriching'")

    # Settings columns for enrichment master toggle + per-source keys.
    op.add_column(
        "settings",
        sa.Column(
            "enrichment_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("settings", sa.Column("enrichment_twitter_api_key_enc", sa.String(), nullable=True))
    op.add_column("settings", sa.Column("enrichment_youtube_api_key_enc", sa.String(), nullable=True))
    op.add_column("settings", sa.Column("enrichment_stackexchange_key_enc", sa.String(), nullable=True))
    # Per-source toggles. JSON dict keyed by source name → bool. Default
    # all-on; spec says default enable all 10 sources.
    op.add_column(
        "settings",
        sa.Column(
            "enrichment_sources",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json")
            if False  # leave dict empty by default; the API layer fills with defaults
            else sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("settings", "enrichment_sources")
    op.drop_column("settings", "enrichment_stackexchange_key_enc")
    op.drop_column("settings", "enrichment_youtube_api_key_enc")
    op.drop_column("settings", "enrichment_twitter_api_key_enc")
    op.drop_column("settings", "enrichment_enabled")
    # Postgres has no clean way to remove an enum value; we leave the
    # 'enriching' label in place on downgrade. Acceptable per Alembic docs.
    op.drop_column("jobs", "enrichment_consent")
    op.drop_column("applications", "enrichment")
```

> **Decision (in-plan):** the per-source toggle map is stored as `enrichment_sources: JSON` rather than 10 individual boolean columns to avoid a wide schema. The API layer (`SettingsRead._sources_with_defaults`) fills missing keys with `True`.

- [ ] **Step 2: Update `Application` model**

In `src/recruiter/models/application.py`:

```python
class Stage(str, Enum):
    SOURCED = "sourced"
    EXTRACTING = "extracting"
    ENRICHING = "enriching"   # NEW — between EXTRACTING and SCORED
    SCORED = "scored"
    VALIDATED = "validated"
    INVITED = "invited"
    SCHEDULED = "scheduled"
    REJECTED = "rejected"
```

Add to `Application`:

```python
    enrichment: Mapped[dict | None] = mapped_column(JSON)
```

- [ ] **Step 3: Update `Job` model**

In `src/recruiter/models/job.py`:

```python
from sqlalchemy import Boolean, JSON, DateTime, Enum as SAEnum, String, func
...
    enrichment_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

- [ ] **Step 4: Update `SettingsRow` model**

In `src/recruiter/models/settings.py`:

```python
from sqlalchemy import Boolean, JSON, CheckConstraint, DateTime, Integer, String, func
...
    enrichment_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enrichment_twitter_api_key_enc: Mapped[str | None] = mapped_column(String)
    enrichment_youtube_api_key_enc: Mapped[str | None] = mapped_column(String)
    enrichment_stackexchange_key_enc: Mapped[str | None] = mapped_column(String)
    enrichment_sources: Mapped[dict] = mapped_column(JSON, default=dict)
```

- [ ] **Step 5: Update `ApplicationRead` schema**

In `src/recruiter/schemas/application.py`:

```python
class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    ...
    enrichment: dict | None = None
```

- [ ] **Step 6: Update `JobRead` / `JobCreate` / `JobUpdate` schemas**

In `src/recruiter/schemas/job.py`:

```python
class JobCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    criteria: list[CriteriaItem] = Field(default_factory=list)
    enrichment_consent: bool = False


class JobUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    criteria: list[CriteriaItem] | None = None
    status: str | None = None
    enrichment_consent: bool | None = None


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    ...
    enrichment_consent: bool = False
```

Update the `_to_read` helper in `src/recruiter/api/jobs.py` to include the new field, and the create/update handlers to persist it.

- [ ] **Step 7: Round-trip test**

Create `tests/unit/test_enrichment_models.py`:

```python
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.models import Application, Candidate, Job, Stage


@pytest.mark.asyncio
async def test_application_enrichment_field_round_trips(session: AsyncSession) -> None:
    """The new JSON column survives a write/read cycle."""
    job = Job(title="t", description="d", criteria=[], enrichment_consent=True)
    cand = Candidate(full_name="Alice")
    session.add_all([job, cand])
    await session.flush()
    app = Application(
        job_id=job.id,
        candidate_id=cand.id,
        stage=Stage.ENRICHING,
        enrichment={"results": [{"source": "github", "confidence": 1.0}]},
    )
    session.add(app)
    await session.commit()

    fetched = (
        await session.execute(select(Application).where(Application.id == app.id))
    ).scalar_one()
    assert fetched.stage == Stage.ENRICHING
    assert fetched.enrichment == {"results": [{"source": "github", "confidence": 1.0}]}


@pytest.mark.asyncio
async def test_application_enrichment_defaults_to_none(session: AsyncSession) -> None:
    job = Job(title="t", description="d", criteria=[])
    cand = Candidate()
    session.add_all([job, cand])
    await session.flush()
    app = Application(job_id=job.id, candidate_id=cand.id, stage=Stage.EXTRACTING)
    session.add(app)
    await session.commit()
    assert app.enrichment is None


@pytest.mark.asyncio
async def test_job_enrichment_consent_default_false(session: AsyncSession) -> None:
    job = Job(title="t", description="d", criteria=[])
    session.add(job)
    await session.commit()
    assert job.enrichment_consent is False


def test_stage_enum_includes_enriching() -> None:
    assert Stage.ENRICHING.value == "enriching"
    assert Stage("enriching") is Stage.ENRICHING
```

(The `session` fixture exists already — see `tests/conftest.py`.)

- [ ] **Step 8: Run the migration + tests**

```bash
uv run alembic upgrade head
uv run pytest tests/unit/test_enrichment_models.py -v
```

Expected: migration applies cleanly, all 4 tests PASS.

- [ ] **Step 9: Run the full unit suite to confirm no regressions**

```bash
uv run pytest tests/unit -x
```

Expected: all PASS (any pre-existing failures noted in T32 — none expected from this task).

- [ ] **Step 10: Commit**

```bash
git add alembic/versions/*_add_enrichment_columns.py \
        src/recruiter/models/application.py \
        src/recruiter/models/job.py \
        src/recruiter/models/settings.py \
        src/recruiter/schemas/application.py \
        src/recruiter/schemas/job.py \
        src/recruiter/api/jobs.py \
        tests/unit/test_enrichment_models.py
git commit -m "feat(enrichment): add Application.enrichment, Job.enrichment_consent, Stage.ENRICHING"
```

---

### Task 2: `enrichment/provider.py` — Protocol, schemas, registry

**Files:**
- Create: `src/recruiter/enrichment/__init__.py` (empty for now; provider modules will be appended later)
- Create: `src/recruiter/enrichment/provider.py`
- Create: `tests/unit/test_enrichment_registry.py`

- [ ] **Step 1: Write the failing test file**

Create `tests/unit/test_enrichment_registry.py`:

```python
import pytest

from recruiter.enrichment.provider import (
    EnrichmentBundle,
    EnrichmentHint,
    EnrichmentResult,
    EnrichmentSignal,
    register,
    resolve_all,
    _REGISTRY,
)


def test_signal_schema_validates() -> None:
    s = EnrichmentSignal(type="post", summary="Wrote about Rust async", url="https://example/")
    assert s.type == "post"
    assert s.url == "https://example/"


def test_result_schema_round_trips() -> None:
    r = EnrichmentResult(
        source="github",
        profile_url="https://github.com/alice",
        confidence=1.0,
        discovered=False,
        signals=[EnrichmentSignal(type="code", summary="rust-lang/rust contributor")],
        summary="Active GitHub contributor.",
    )
    assert r.confidence == 1.0
    assert len(r.signals) == 1


def test_hint_accepts_url_or_name_employer() -> None:
    h1 = EnrichmentHint(url="https://github.com/alice", confidence=1.0)
    h2 = EnrichmentHint(name="Alice Doe", employer="Acme", confidence=0.5)
    assert h1.url and not h1.name
    assert h2.name and not h2.url


def test_register_decorator_adds_to_global_registry() -> None:
    # Save and restore registry to keep this test hermetic.
    saved = dict(_REGISTRY)
    try:
        _REGISTRY.clear()

        @register("dummy")
        class _Dummy:
            name = "dummy"
            domains = ["dummy.example"]

            async def enrich(self, hint):
                return None

        assert "dummy" in _REGISTRY
        assert _REGISTRY["dummy"] is _Dummy
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(saved)


def test_resolve_all_filters_by_settings_toggles() -> None:
    saved = dict(_REGISTRY)
    try:
        _REGISTRY.clear()

        @register("a")
        class _A:
            name = "a"
            domains = ["a.example"]
            def __init__(self, *_, **__): pass
            async def enrich(self, hint): return None

        @register("b")
        class _B:
            name = "b"
            domains = ["b.example"]
            def __init__(self, *_, **__): pass
            async def enrich(self, hint): return None

        # Settings shape: per-source dict in `enrichment_sources`. Missing
        # key → enabled (default True). Explicit False → skipped.
        fake_settings = type("S", (), {
            "enrichment_sources": {"b": False},
            "enrichment_twitter_api_key_enc": None,
            "enrichment_youtube_api_key_enc": None,
            "enrichment_stackexchange_key_enc": None,
            "github_token_enc": None,
        })()
        out = resolve_all(fake_settings)
        names = [p.name for p in out]
        assert "a" in names
        assert "b" not in names
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(saved)


def test_bundle_schema_holds_results_and_errors() -> None:
    from datetime import datetime, timezone
    b = EnrichmentBundle(
        fetched_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc),
        discovery_consent=True,
        results=[],
        errors=[{"source": "twitter", "error": "401", "transient": False}],
    )
    assert b.discovery_consent is True
    assert b.errors[0]["source"] == "twitter"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/unit/test_enrichment_registry.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'recruiter.enrichment'`.

- [ ] **Step 3: Create the package**

Create `src/recruiter/enrichment/__init__.py` with:

```python
# Provider module imports get appended here as each @register-decorated
# class lands. Empty until T5 adds the first provider (Hacker News).
```

- [ ] **Step 4: Implement provider.py**

Create `src/recruiter/enrichment/provider.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


# ---------- schemas ----------


class EnrichmentSignal(BaseModel):
    type: Literal["code", "answer", "post", "talk", "writing", "profile"]
    summary: str
    url: str | None = None
    timestamp: datetime | None = None


class EnrichmentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    profile_url: str
    confidence: float          # 0.0..1.0
    discovered: bool           # True if found via discovery, False if from candidate.links
    signals: list[EnrichmentSignal]
    summary: str               # one-paragraph overview, recruiter-facing


class EnrichmentBundle(BaseModel):
    fetched_at: datetime
    expires_at: datetime
    discovery_consent: bool
    results: list[EnrichmentResult]
    errors: list[dict]         # { source, error, transient }


class EnrichmentHint(BaseModel):
    """Input shape for a provider. Either an explicit URL (confidence 1.0)
    or a name+employer pair from discovery (confidence 0.5)."""
    url: str | None = None
    name: str | None = None
    employer: str | None = None
    confidence: float = 0.5
    source: str | None = None  # which provider this hint targets, if known

    def model_post_init(self, _ctx) -> None:
        if not self.url and not self.name:
            raise ValueError("EnrichmentHint requires url or name")


# ---------- protocol ----------


@runtime_checkable
class EnrichmentProvider(Protocol):
    name: ClassVar[str]
    domains: ClassVar[list[str]]

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None: ...

    async def aclose(self) -> None: ...


# ---------- registry ----------


_REGISTRY: dict[str, type] = {}


def register(name: str):
    """Class decorator. Registers a provider class under `name`. Each provider
    module imports `register` and decorates its top-level provider class."""
    def deco(cls: type) -> type:
        _REGISTRY[name] = cls
        return cls
    return deco


def _instantiate(cls: type, settings: Any) -> EnrichmentProvider | None:
    """Build a provider instance from settings. Each provider class accepts
    optional kwargs (api_key, token, etc.) — the loader resolves them per
    provider name. Returns None when required config is missing."""
    from recruiter.crypto import settings_cipher

    cipher = settings_cipher()
    name = getattr(cls, "name", None)
    try:
        if name == "twitter":
            enc = getattr(settings, "enrichment_twitter_api_key_enc", None)
            if not enc:
                return None
            return cls(bearer_token=cipher.decrypt(enc))
        if name == "youtube":
            enc = getattr(settings, "enrichment_youtube_api_key_enc", None)
            if not enc:
                return None
            return cls(api_key=cipher.decrypt(enc))
        if name == "stackoverflow":
            enc = getattr(settings, "enrichment_stackexchange_key_enc", None)
            return cls(api_key=cipher.decrypt(enc) if enc else None)
        if name == "github":
            enc = getattr(settings, "github_token_enc", None)
            return cls(token=cipher.decrypt(enc) if enc else None)
        # Keyless providers: hackernews, reddit, mastodon, bluesky, devto, blog.
        return cls()
    except Exception:
        # A bad/corrupted ciphertext shouldn't take down the whole pipeline.
        return None


def resolve_all(settings: Any) -> list[EnrichmentProvider]:
    """Return one configured instance per registered provider, filtered by
    `settings.enrichment_sources` (dict of name → bool; missing → True)
    and by required-config presence."""
    toggles: dict[str, bool] = getattr(settings, "enrichment_sources", None) or {}
    out: list[EnrichmentProvider] = []
    for name, cls in _REGISTRY.items():
        if toggles.get(name, True) is False:
            continue
        inst = _instantiate(cls, settings)
        if inst is None:
            continue
        out.append(inst)
    return out


def resolve_for_domain(domain: str, settings: Any) -> EnrichmentProvider | None:
    """Return the single provider whose `domains` list matches the given
    URL host, or None if no provider claims it. Used by the pipeline when
    routing an explicit hint URL to its handler."""
    for prov in resolve_all(settings):
        for d in prov.domains:
            if domain == d or domain.endswith("." + d):
                return prov
    return None
```

- [ ] **Step 5: Re-run tests, expect green**

```bash
uv run pytest tests/unit/test_enrichment_registry.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/recruiter/enrichment/__init__.py \
        src/recruiter/enrichment/provider.py \
        tests/unit/test_enrichment_registry.py
git commit -m "feat(enrichment): add provider Protocol, schemas, and registry"
```

---

### Task 3: `enrichment/identity.py` — confidence engine

**Files:**
- Create: `src/recruiter/enrichment/identity.py`
- Create: `tests/unit/test_enrichment_identity.py`

Pure-function module. Builds a graph from a list of `EnrichmentResult`, propagates confidence per the spec's "Confidence tiers" + "Cross-corroboration rules" sections. No I/O.

**Algorithm summary** (from spec):

- Inputs: list of `EnrichmentResult`, plus the candidate's known emails and explicit links (confidence-1.0 anchors).
- Each result starts at its declared confidence (1.0 / 0.8 / 0.5 / 0.75 — set by the provider).
- Rules:
  1. A profile that explicitly links to another already-confirmed (≥0.8) profile inherits 0.8.
  2. A profile whose username exactly matches a confirmed-profile username on another platform earns +0.2 (capped at 0.8).
  3. A profile whose email/website on the public page matches the candidate's email or a 1.0 link earns +0.3.
  4. Final results <0.5 are discarded.
- Iterate until no confidence changes (fixed point), max 5 iterations.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_enrichment_identity.py`:

```python
from datetime import datetime, timezone

from recruiter.enrichment.identity import consolidate
from recruiter.enrichment.provider import EnrichmentResult, EnrichmentSignal


def _result(source: str, *, confidence: float, profile_url: str, signals=None, summary="x") -> EnrichmentResult:
    return EnrichmentResult(
        source=source,
        profile_url=profile_url,
        confidence=confidence,
        discovered=False,
        signals=signals or [],
        summary=summary,
    )


def test_anchored_url_keeps_confidence_1_0() -> None:
    """A 1.0 result (explicit candidate.link) is unchanged."""
    r = _result("github", confidence=1.0, profile_url="https://github.com/alice")
    out = consolidate([r], anchor_urls=["https://github.com/alice"], anchor_emails=[])
    assert out[0].confidence == 1.0


def test_discovered_result_with_no_corroboration_stays_low() -> None:
    r = _result("mastodon", confidence=0.5, profile_url="https://mastodon.social/@alice")
    out = consolidate([r], anchor_urls=[], anchor_emails=[])
    assert out[0].confidence == 0.5


def test_username_match_with_anchor_promotes_to_0_8() -> None:
    """Mastodon @alice when GitHub anchor is github.com/alice → +0.2 → 0.7,
    but spec says cap at 0.8 only after additional corroboration; matching
    username alone gives +0.2 to a 0.5 base = 0.7."""
    r = _result("mastodon", confidence=0.5, profile_url="https://mastodon.social/@alice")
    out = consolidate([r], anchor_urls=["https://github.com/alice"], anchor_emails=[])
    assert out[0].confidence == pytest.approx(0.7)


def test_username_match_plus_email_match_caps_at_0_8() -> None:
    """+0.2 (username) +0.3 (email) on top of 0.5 = 1.0, capped at 0.8 per spec."""
    r = _result(
        "mastodon",
        confidence=0.5,
        profile_url="https://mastodon.social/@alice",
        signals=[EnrichmentSignal(type="profile", summary="alice@acme.com on profile page")],
    )
    out = consolidate(
        [r],
        anchor_urls=["https://github.com/alice"],
        anchor_emails=["alice@acme.com"],
    )
    assert out[0].confidence == pytest.approx(0.8)


def test_explicit_cross_link_propagates_0_8() -> None:
    """Mastodon profile bio explicitly links to confirmed GitHub → 0.8."""
    confirmed_gh = _result("github", confidence=1.0, profile_url="https://github.com/alice")
    masto = _result(
        "mastodon",
        confidence=0.5,
        profile_url="https://fosstodon.org/@alice",
        signals=[EnrichmentSignal(type="profile", summary="bio links https://github.com/alice")],
    )
    out = consolidate([confirmed_gh, masto], anchor_urls=["https://github.com/alice"], anchor_emails=[])
    masto_out = next(r for r in out if r.source == "mastodon")
    assert masto_out.confidence == pytest.approx(0.8)


def test_below_0_5_results_are_dropped() -> None:
    r = _result("reddit", confidence=0.3, profile_url="https://reddit.com/u/alice")
    out = consolidate([r], anchor_urls=[], anchor_emails=[])
    assert out == []


def test_two_independent_discovered_results_corroborate_to_0_75() -> None:
    """Spec table: discovered (0.5) + corroborated by ≥2 independent sources → 0.75."""
    r1 = _result("hackernews", confidence=0.5, profile_url="https://news.ycombinator.com/user?id=alice")
    r2 = _result("devto", confidence=0.5, profile_url="https://dev.to/alice")
    r3 = _result("stackoverflow", confidence=0.5, profile_url="https://stackoverflow.com/u/alice")
    out = consolidate([r1, r2, r3], anchor_urls=[], anchor_emails=[])
    # All three share username "alice" — each one is corroborated by the
    # other two. Per spec, ≥2 corroborations → 0.75.
    for r in out:
        assert r.confidence == pytest.approx(0.75)


def test_fixed_point_iteration_terminates() -> None:
    """Many cross-references → engine must not infinite-loop."""
    rs = [
        _result(f"src{i}", confidence=0.5, profile_url=f"https://x{i}.example/u/alice")
        for i in range(8)
    ]
    out = consolidate(rs, anchor_urls=["https://github.com/alice"], anchor_emails=[])
    assert all(r.confidence >= 0.5 for r in out)


def test_pure_function_does_not_mutate_inputs() -> None:
    r = _result("github", confidence=1.0, profile_url="https://github.com/alice")
    inputs = [r]
    consolidate(inputs, anchor_urls=[], anchor_emails=[])
    assert inputs[0].confidence == 1.0
    assert len(inputs) == 1


def test_empty_input_returns_empty_list() -> None:
    assert consolidate([], anchor_urls=[], anchor_emails=[]) == []


def test_username_extraction_handles_at_sign_variants() -> None:
    """Mastodon-style @alice and dev.to-style /alice both extract to 'alice'."""
    r1 = _result("mastodon", confidence=0.5, profile_url="https://mastodon.social/@alice")
    r2 = _result("devto", confidence=0.5, profile_url="https://dev.to/alice")
    out = consolidate([r1, r2], anchor_urls=["https://github.com/alice"], anchor_emails=[])
    # Both should hit the username-match rule and clear 0.5.
    assert all(r.confidence > 0.5 for r in out)


def test_email_in_signals_text_is_recognized() -> None:
    r = _result(
        "blog",
        confidence=0.5,
        profile_url="https://alice.dev",
        signals=[EnrichmentSignal(type="profile", summary="contact: alice@acme.com")],
    )
    out = consolidate([r], anchor_urls=[], anchor_emails=["alice@acme.com"])
    assert out[0].confidence == pytest.approx(0.8)


def test_anchor_email_with_no_match_does_not_promote() -> None:
    r = _result("blog", confidence=0.5, profile_url="https://stranger.dev",
                signals=[EnrichmentSignal(type="profile", summary="no email here")])
    out = consolidate([r], anchor_urls=[], anchor_emails=["alice@acme.com"])
    assert out[0].confidence == 0.5


def test_provider_supplied_high_confidence_is_preserved() -> None:
    """Provider claimed 1.0 (URL was in candidate.links); engine never lowers."""
    r = _result("github", confidence=1.0, profile_url="https://github.com/alice")
    out = consolidate([r], anchor_urls=[], anchor_emails=[])
    assert out[0].confidence == 1.0


def test_three_independent_corroborations_do_not_exceed_cap() -> None:
    rs = [
        _result(f"s{i}", confidence=0.5, profile_url=f"https://x{i}.example/u/alice")
        for i in range(3)
    ]
    out = consolidate(rs, anchor_urls=["https://github.com/alice"], anchor_emails=[])
    assert all(r.confidence <= 0.8 + 1e-9 for r in out)
```

> Note: add `import pytest` at the top of the test file.

- [ ] **Step 2: Implement `consolidate`**

Create `src/recruiter/enrichment/identity.py`:

```python
from __future__ import annotations

import re
from urllib.parse import urlparse

from recruiter.enrichment.provider import EnrichmentResult


_USERNAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,38}")


def _extract_username(url: str) -> str | None:
    """Best-effort username extraction across our supported profile URL shapes:
    github.com/<u>, dev.to/<u>, stackoverflow.com/u/<id>/<slug>,
    mastodon.social/@<u>, news.ycombinator.com/user?id=<u>, etc."""
    if not url:
        return None
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    qs = parsed.query
    if path.startswith("@"):
        return path[1:].split("/")[0] or None
    if "user?id=" in qs:
        m = re.search(r"id=([A-Za-z0-9._-]+)", qs)
        return m.group(1) if m else None
    if path.startswith("u/") or path.startswith("user/"):
        parts = path.split("/")
        if len(parts) >= 2:
            # stackoverflow.com/u/<id>/<slug-name> — prefer the slug name when present.
            return parts[2] if len(parts) >= 3 and parts[2] else parts[1]
    parts = path.split("/")
    return parts[0] if parts and parts[0] else None


def _emails_in_signals(result: EnrichmentResult) -> set[str]:
    emails: set[str] = set()
    for sig in result.signals:
        for m in re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", sig.summary or ""):
            emails.add(m.lower())
    for m in re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", result.summary or ""):
        emails.add(m.lower())
    return emails


def _explicit_links_in_signals(result: EnrichmentResult) -> list[str]:
    out: list[str] = []
    for sig in result.signals:
        out.extend(re.findall(r"https?://[^\s)]+", sig.summary or ""))
    out.extend(re.findall(r"https?://[^\s)]+", result.summary or ""))
    return out


def consolidate(
    results: list[EnrichmentResult],
    *,
    anchor_urls: list[str],
    anchor_emails: list[str],
) -> list[EnrichmentResult]:
    """Pure-function confidence propagation.

    - 1.0 anchors (candidate.links) are passed in via `anchor_urls`. The
      provider has already labeled those results 1.0; we use them to seed
      "confirmed-username" / "confirmed-domain" sets used in the rules.
    - Iterate until fixed point (max 5 passes), then drop <0.5.
    - Cap promotions at 0.8 (only provider-supplied 1.0 may be higher).
    """
    # Defensive copy so we don't mutate caller-owned objects.
    out = [r.model_copy(deep=True) for r in results]

    confirmed_usernames: set[str] = set()
    for u in anchor_urls:
        un = _extract_username(u)
        if un:
            confirmed_usernames.add(un.lower())
    # Provider-anchored (confidence 1.0) results add to confirmed pool too.
    for r in out:
        if r.confidence >= 1.0:
            un = _extract_username(r.profile_url)
            if un:
                confirmed_usernames.add(un.lower())

    anchor_email_set = {e.lower() for e in anchor_emails}
    anchor_url_set = {u.lower() for u in anchor_urls}

    for _ in range(5):
        changed = False
        # Re-derive corroboration sets each pass — promotions in pass N let
        # pass N+1 cross-link further.
        confirmed_now = set(confirmed_usernames)
        confirmed_links: set[str] = set(anchor_url_set)
        for r in out:
            if r.confidence >= 0.8:
                un = _extract_username(r.profile_url)
                if un:
                    confirmed_now.add(un.lower())
                confirmed_links.add(r.profile_url.lower())

        for r in out:
            if r.confidence >= 1.0:
                continue  # never lower or re-promote anchors

            base = r.confidence
            bonus = 0.0
            un = _extract_username(r.profile_url)

            # Rule 2: username exact-matches a confirmed username (other platform).
            if un and un.lower() in confirmed_now:
                # Don't reward a profile for matching its own confirmed entry —
                # only count a *different* source's confirmation.
                if base < 0.8:
                    bonus += 0.2

            # Rule 3: email/website on the page matches a candidate email
            # or a 1.0-anchor link.
            page_emails = _emails_in_signals(r)
            if page_emails & anchor_email_set:
                bonus += 0.3
            page_links = {u.lower() for u in _explicit_links_in_signals(r)}
            if page_links & confirmed_links:
                # Rule 1: explicit cross-link to a confirmed profile → at
                # least 0.8 floor.
                base = max(base, 0.8)

            # ≥2 independent corroborations → bump 0.5 base to 0.75.
            other_sources_with_same_username = 0
            if un:
                for other in out:
                    if other is r or other.source == r.source:
                        continue
                    other_un = _extract_username(other.profile_url)
                    if other_un and other_un.lower() == un.lower():
                        other_sources_with_same_username += 1
            if other_sources_with_same_username >= 2 and base == 0.5:
                base = 0.75

            new_conf = min(0.8, base + bonus) if base < 1.0 else base
            if abs(new_conf - r.confidence) > 1e-9:
                r.confidence = new_conf
                changed = True

        if not changed:
            break

    return [r for r in out if r.confidence >= 0.5]
```

> **Decision (in-plan):** the "≥2 independent sources" rule from the spec maps to ≥2 *other* providers sharing the same username slug. We use the slug from the profile URL as the cross-platform key. Edge case: providers whose URL shape doesn't expose a username (e.g., Stack Overflow's numeric `/u/123/`) extract the slug name instead.

- [ ] **Step 3: Run the tests**

```bash
uv run pytest tests/unit/test_enrichment_identity.py -v
```

Expected: all 15 tests PASS. If a test fails, adjust the rule weighting in `consolidate` — the test cases pin the spec semantics.

- [ ] **Step 4: Commit**

```bash
git add src/recruiter/enrichment/identity.py tests/unit/test_enrichment_identity.py
git commit -m "feat(enrichment): add identity confidence engine"
```

---

## Provider tasks — shared structure

Each provider task pair (red → green) follows the brave-searxng cadence. To avoid repeating boilerplate, reference these snippets that every provider's test file shares:

```python
# top of every tests/unit/test_enrichment_<name>.py
import httpx
import pytest

from recruiter.enrichment.provider import EnrichmentHint
from recruiter.enrichment.<name> import <Name>Provider


def _make_provider(transport: httpx.MockTransport, **kwargs) -> <Name>Provider:
    return <Name>Provider(transport=transport, **kwargs)
```

Every provider implements the Protocol (`name`, `domains`, `enrich`, `aclose`) and is wrapped by a top-level class decorator `@register("<name>")`. The class signature is always:

```python
@register("<name>")
class <Name>Provider:
    name: ClassVar[str] = "<name>"
    domains: ClassVar[list[str]] = [...]

    def __init__(self, *, <key>=None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        ...
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        ...
```

When a provider's `enrich` can't resolve a username from the hint (e.g., a name+employer hint without enough context), it returns `None` and the pipeline simply skips it. Network/auth errors should be caught locally and returned as `None` after logging — providers do **not** raise into the pipeline (per spec: "missing/failed enrichment is non-fatal").

Each provider's `__init__.py` registration import gets appended to `src/recruiter/enrichment/__init__.py` in the green-step commit:

```python
from recruiter.enrichment import <name> as _<name>  # noqa: F401
```

---

### Task 4: Hacker News — failing tests

**Files:**
- Create: `tests/unit/test_enrichment_hackernews.py`

API: `https://hn.algolia.com/api/v1/search?tags=story,author_<u>` (and `tags=comment,author_<u>` for comments). No key.

- [ ] **Step 1: Write the test file**

```python
import httpx
import pytest

from recruiter.enrichment.hackernews import HackerNewsProvider
from recruiter.enrichment.provider import EnrichmentHint


def _make_provider(transport: httpx.MockTransport) -> HackerNewsProvider:
    return HackerNewsProvider(transport=transport)


@pytest.mark.asyncio
async def test_enrich_returns_signals_for_known_user() -> None:
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.setdefault("paths", []).append(req.url.path)
        seen.setdefault("queries", []).append(dict(req.url.params))
        if "tags" in req.url.params and "story" in req.url.params["tags"]:
            return httpx.Response(200, json={
                "hits": [
                    {
                        "objectID": "1",
                        "title": "Show HN: my Rust crate",
                        "url": "https://news.ycombinator.com/item?id=1",
                        "created_at": "2025-04-01T12:00:00Z",
                        "points": 42,
                    },
                ],
                "nbHits": 1,
            })
        return httpx.Response(200, json={"hits": [], "nbHits": 0})

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://news.ycombinator.com/user?id=alice", confidence=1.0)
    result = await p.enrich(hint)
    assert result is not None
    assert result.source == "hackernews"
    assert result.profile_url == "https://news.ycombinator.com/user?id=alice"
    assert result.confidence == 1.0
    assert any("Show HN" in s.summary for s in result.signals)
    # Must hit the Algolia search endpoint.
    assert any("hn.algolia.com" in p_ for p_ in [str(req) for req in seen.get("paths", [])]) or any(
        "/api/v1/search" in p_ for p_ in seen.get("paths", [])
    )


@pytest.mark.asyncio
async def test_enrich_returns_none_when_user_has_no_activity() -> None:
    handler = lambda req: httpx.Response(200, json={"hits": [], "nbHits": 0})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://news.ycombinator.com/user?id=ghost", confidence=1.0)
    result = await p.enrich(hint)
    assert result is None


@pytest.mark.asyncio
async def test_enrich_handles_missing_fields_gracefully() -> None:
    handler = lambda req: httpx.Response(200, json={
        "hits": [{"objectID": "x"}],  # no title, no url, no timestamp
        "nbHits": 1,
    })
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://news.ycombinator.com/user?id=alice", confidence=1.0)
    result = await p.enrich(hint)
    # Provider must not crash on partial responses; it can still return a
    # result with a generic signal or skip the malformed item.
    assert result is None or len(result.signals) <= 1


@pytest.mark.asyncio
async def test_enrich_returns_none_on_network_failure() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://news.ycombinator.com/user?id=alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_5xx() -> None:
    handler = lambda req: httpx.Response(503, text="bad")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://news.ycombinator.com/user?id=alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_429() -> None:
    handler = lambda req: httpx.Response(429, text="rate")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://news.ycombinator.com/user?id=alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_caps_signals_at_5() -> None:
    handler = lambda req: httpx.Response(200, json={
        "hits": [
            {"objectID": str(i), "title": f"post {i}", "url": f"https://hn/{i}", "created_at": "2025-01-01T00:00:00Z"}
            for i in range(20)
        ],
        "nbHits": 20,
    })
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://news.ycombinator.com/user?id=alice", confidence=1.0)
    result = await p.enrich(hint)
    assert result is not None
    assert len(result.signals) <= 5


@pytest.mark.asyncio
async def test_enrich_propagates_hint_confidence() -> None:
    handler = lambda req: httpx.Response(200, json={
        "hits": [{"objectID": "1", "title": "x", "url": "https://hn/1", "created_at": "2025-01-01T00:00:00Z"}],
        "nbHits": 1,
    })
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://news.ycombinator.com/user?id=alice", confidence=0.5)
    result = await p.enrich(hint)
    assert result is not None
    assert result.confidence == 0.5
    assert result.discovered  # confidence < 1.0 => discovered


@pytest.mark.asyncio
async def test_enrich_with_name_only_hint_returns_none() -> None:
    """HN provider needs a username; a bare-name discovery hint is unactionable."""
    handler = lambda req: httpx.Response(200, json={"hits": [], "nbHits": 0})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(name="Alice Doe", confidence=0.5)
    assert await p.enrich(hint) is None
```

- [ ] **Step 2: Run, expect failure**

```bash
uv run pytest tests/unit/test_enrichment_hackernews.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'recruiter.enrichment.hackernews'`.

---

### Task 5: Hacker News — implementation

**Files:**
- Create: `src/recruiter/enrichment/hackernews.py`
- Modify: `src/recruiter/enrichment/__init__.py`

- [ ] **Step 1: Implementation**

```python
from __future__ import annotations

import logging
from typing import ClassVar
from urllib.parse import urlparse, parse_qs

import httpx

from recruiter.enrichment.provider import (
    EnrichmentHint,
    EnrichmentResult,
    EnrichmentSignal,
    register,
)

logger = logging.getLogger(__name__)

HN_SEARCH = "https://hn.algolia.com/api/v1/search"


def _username_from_hn_url(url: str) -> str | None:
    parsed = urlparse(url)
    if "news.ycombinator.com" not in (parsed.hostname or ""):
        return None
    qs = parse_qs(parsed.query)
    if "id" in qs:
        return qs["id"][0]
    return None


@register("hackernews")
class HackerNewsProvider:
    name: ClassVar[str] = "hackernews"
    domains: ClassVar[list[str]] = ["news.ycombinator.com"]

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        username: str | None = None
        if hint.url:
            username = _username_from_hn_url(hint.url)
        if not username:
            return None
        profile_url = f"https://news.ycombinator.com/user?id={username}"

        try:
            r = await self._client.get(
                HN_SEARCH,
                params={"tags": f"story,author_{username}", "hitsPerPage": 5},
            )
        except httpx.HTTPError as exc:
            logger.info("hackernews fetch failed for %s: %s", username, exc)
            return None
        if r.status_code != 200:
            logger.info("hackernews returned %s for %s", r.status_code, username)
            return None

        try:
            payload = r.json()
        except ValueError:
            return None

        hits = payload.get("hits") or []
        signals: list[EnrichmentSignal] = []
        for h in hits[:5]:
            title = h.get("title")
            url = h.get("url") or (
                f"https://news.ycombinator.com/item?id={h['objectID']}"
                if h.get("objectID") else None
            )
            ts = h.get("created_at")
            if not title:
                continue
            from datetime import datetime
            try:
                ts_parsed = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
            except (ValueError, AttributeError):
                ts_parsed = None
            signals.append(EnrichmentSignal(
                type="post",
                summary=f'HN story: "{title}" ({h.get("points", 0)} points)',
                url=url,
                timestamp=ts_parsed,
            ))

        if not signals:
            return None

        summary = (
            f"Active on Hacker News as {username}: {len(hits)} stories. "
            f"Top: {signals[0].summary[:120]}"
        )
        return EnrichmentResult(
            source="hackernews",
            profile_url=profile_url,
            confidence=hint.confidence,
            discovered=hint.confidence < 1.0,
            signals=signals,
            summary=summary,
        )
```

- [ ] **Step 2: Wire registration import**

Append to `src/recruiter/enrichment/__init__.py`:

```python
from recruiter.enrichment import hackernews as _hackernews  # noqa: F401
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/unit/test_enrichment_hackernews.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add src/recruiter/enrichment/hackernews.py \
        src/recruiter/enrichment/__init__.py \
        tests/unit/test_enrichment_hackernews.py
git commit -m "feat(enrichment): add Hacker News provider"
```

---

### Task 6: Reddit — failing tests

**Files:**
- Create: `tests/unit/test_enrichment_reddit.py`

API: `https://www.reddit.com/user/<u>/about.json` + `/user/<u>/comments.json?limit=10`. No key. 60/min unauthenticated.

- [ ] **Step 1: Write the test file**

```python
import httpx
import pytest

from recruiter.enrichment.provider import EnrichmentHint
from recruiter.enrichment.reddit import RedditProvider


def _make_provider(transport: httpx.MockTransport) -> RedditProvider:
    return RedditProvider(transport=transport)


def _about(karma: int = 1234) -> dict:
    return {
        "data": {
            "name": "alice",
            "link_karma": karma,
            "comment_karma": 567,
            "created_utc": 1577836800.0,  # 2020-01-01
            "subreddit": {"public_description": "Software engineer"},
        }
    }


def _comments(items: list[dict] | None = None) -> dict:
    return {
        "data": {
            "children": [
                {"data": item}
                for item in (items or [])
            ]
        }
    }


@pytest.mark.asyncio
async def test_enrich_returns_signals_for_known_user() -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        if req.url.path.endswith("/about.json"):
            return httpx.Response(200, json=_about())
        if req.url.path.endswith("/comments.json"):
            return httpx.Response(200, json=_comments([
                {"body": "Use tokio for async Rust", "subreddit": "rust",
                 "permalink": "/r/rust/c/1", "created_utc": 1700000000.0, "score": 12},
                {"body": "Postgres beats MySQL for OLTP", "subreddit": "Database",
                 "permalink": "/r/Database/c/2", "created_utc": 1700001000.0, "score": 5},
            ]))
        return httpx.Response(404)

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.reddit.com/user/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert r.source == "reddit"
    assert r.profile_url == "https://www.reddit.com/user/alice"
    assert r.confidence == 1.0
    assert any("/about.json" in p_ for p_ in paths)
    assert any("/comments.json" in p_ for p_ in paths)
    # Public bio + 2 comments → at least 2 signals.
    assert len(r.signals) >= 2


@pytest.mark.asyncio
async def test_enrich_returns_none_on_404() -> None:
    handler = lambda req: httpx.Response(404, text="not found")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://reddit.com/u/ghost", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_handles_old_reddit_url_form() -> None:
    """old.reddit.com/u/<u> should resolve the same username."""
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/about.json"):
            return httpx.Response(200, json=_about())
        return httpx.Response(200, json=_comments([]))

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://old.reddit.com/u/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert "alice" in r.profile_url


@pytest.mark.asyncio
async def test_enrich_returns_none_on_429() -> None:
    handler = lambda req: httpx.Response(429, text="rate")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.reddit.com/u/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_5xx() -> None:
    handler = lambda req: httpx.Response(503, text="oops")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.reddit.com/u/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_network_failure() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.reddit.com/u/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_propagates_low_confidence_hint() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/about.json"):
            return httpx.Response(200, json=_about())
        return httpx.Response(200, json=_comments([
            {"body": "x", "subreddit": "x", "permalink": "/r/x/1", "created_utc": 1.0, "score": 0}
        ]))

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.reddit.com/u/alice", confidence=0.5)
    r = await p.enrich(hint)
    assert r is not None and r.confidence == 0.5 and r.discovered


@pytest.mark.asyncio
async def test_enrich_caps_signals_at_5() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/about.json"):
            return httpx.Response(200, json=_about())
        return httpx.Response(200, json=_comments([
            {"body": f"comment {i}", "subreddit": "x", "permalink": f"/r/x/{i}",
             "created_utc": 1.0, "score": 0}
            for i in range(20)
        ]))

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.reddit.com/u/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert len(r.signals) <= 5


@pytest.mark.asyncio
async def test_enrich_with_name_only_hint_returns_none() -> None:
    handler = lambda req: httpx.Response(200, json={})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(name="Alice Doe", confidence=0.5)
    assert await p.enrich(hint) is None
```

- [ ] **Step 2: Run, expect failure**

```bash
uv run pytest tests/unit/test_enrichment_reddit.py -v
```
Expected: FAIL with import error.

---

### Task 7: Reddit — implementation

**Files:**
- Create: `src/recruiter/enrichment/reddit.py`
- Modify: `src/recruiter/enrichment/__init__.py`

- [ ] **Step 1: Implementation**

```python
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import ClassVar

import httpx

from recruiter.enrichment.provider import (
    EnrichmentHint,
    EnrichmentResult,
    EnrichmentSignal,
    register,
)

logger = logging.getLogger(__name__)

UA = "recruiter-agent/0.1 (+https://example.invalid)"


def _username_from_reddit_url(url: str) -> str | None:
    m = re.search(r"reddit\.com/u(?:ser)?/([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else None


@register("reddit")
class RedditProvider:
    name: ClassVar[str] = "reddit"
    domains: ClassVar[list[str]] = ["reddit.com", "old.reddit.com", "www.reddit.com"]

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            transport=transport, timeout=10.0, headers={"User-Agent": UA}
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        username = _username_from_reddit_url(hint.url) if hint.url else None
        if not username:
            return None

        profile_url = f"https://www.reddit.com/user/{username}"
        about_url = f"https://www.reddit.com/user/{username}/about.json"
        comments_url = f"https://www.reddit.com/user/{username}/comments.json?limit=10"

        try:
            about = await self._client.get(about_url)
            comments = await self._client.get(comments_url)
        except httpx.HTTPError as exc:
            logger.info("reddit fetch failed for %s: %s", username, exc)
            return None
        for r in (about, comments):
            if r.status_code != 200:
                logger.info("reddit returned %s for %s", r.status_code, username)
                return None
        try:
            about_data = about.json().get("data", {}) or {}
            children = comments.json().get("data", {}).get("children", []) or []
        except ValueError:
            return None

        signals: list[EnrichmentSignal] = []
        bio = (about_data.get("subreddit") or {}).get("public_description")
        link_k = about_data.get("link_karma")
        cmt_k = about_data.get("comment_karma")
        if link_k is not None or cmt_k is not None:
            signals.append(EnrichmentSignal(
                type="profile",
                summary=f"Reddit profile: {link_k or 0} link karma, {cmt_k or 0} comment karma"
                        + (f". Bio: {bio}" if bio else ""),
                url=profile_url,
            ))
        for c in children[:4]:
            d = c.get("data") or {}
            body = (d.get("body") or "")[:140]
            sub = d.get("subreddit") or "unknown"
            permalink = d.get("permalink")
            url = f"https://www.reddit.com{permalink}" if permalink else None
            ts = d.get("created_utc")
            ts_parsed = (
                datetime.fromtimestamp(ts, tz=timezone.utc) if isinstance(ts, (int, float)) else None
            )
            signals.append(EnrichmentSignal(
                type="post",
                summary=f"r/{sub}: {body}",
                url=url,
                timestamp=ts_parsed,
            ))
        if not signals:
            return None

        summary = f"Reddit user u/{username}; {len(children)} recent comments."
        return EnrichmentResult(
            source="reddit",
            profile_url=profile_url,
            confidence=hint.confidence,
            discovered=hint.confidence < 1.0,
            signals=signals[:5],
            summary=summary,
        )
```

- [ ] **Step 2: Wire registration**

Append to `src/recruiter/enrichment/__init__.py`:

```python
from recruiter.enrichment import reddit as _reddit  # noqa: F401
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/unit/test_enrichment_reddit.py -v
```
Expected: all 9 PASS.

- [ ] **Step 4: Commit**

```bash
git add src/recruiter/enrichment/reddit.py \
        src/recruiter/enrichment/__init__.py \
        tests/unit/test_enrichment_reddit.py
git commit -m "feat(enrichment): add Reddit provider"
```

---

### Task 8: Mastodon — failing tests

**Files:**
- Create: `tests/unit/test_enrichment_mastodon.py`

API: `https://<instance>/api/v1/accounts/lookup?acct=<u>` then `/api/v1/accounts/<id>/statuses?limit=5`. No key. Multi-instance — provider holds a domain whitelist (mastodon.social, fosstodon.org, hachyderm.io, mas.to, infosec.exchange).

- [ ] **Step 1: Write the test file**

```python
import httpx
import pytest

from recruiter.enrichment.mastodon import MastodonProvider, KNOWN_INSTANCES
from recruiter.enrichment.provider import EnrichmentHint


def _make_provider(transport: httpx.MockTransport) -> MastodonProvider:
    return MastodonProvider(transport=transport)


def _account(id_: str = "42") -> dict:
    return {
        "id": id_,
        "username": "alice",
        "acct": "alice",
        "display_name": "Alice Doe",
        "note": "Software engineer. github.com/alice",
        "url": "https://mastodon.social/@alice",
        "followers_count": 123,
        "statuses_count": 456,
    }


def _status(id_: str, content: str = "<p>Hello</p>", created: str = "2025-04-01T12:00:00Z") -> dict:
    return {
        "id": id_,
        "content": content,
        "url": f"https://mastodon.social/@alice/{id_}",
        "created_at": created,
    }


@pytest.mark.asyncio
async def test_enrich_known_account_returns_signals() -> None:
    seen_paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_paths.append(req.url.path)
        if req.url.path == "/api/v1/accounts/lookup":
            return httpx.Response(200, json=_account())
        if req.url.path == "/api/v1/accounts/42/statuses":
            return httpx.Response(200, json=[
                _status("1", content="<p>Just shipped some Rust async code</p>"),
                _status("2", content="<p>Postgres tip: covering indexes</p>"),
            ])
        return httpx.Response(404)

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://mastodon.social/@alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert r.source == "mastodon"
    assert r.confidence == 1.0
    assert len(r.signals) >= 2
    assert "/api/v1/accounts/lookup" in seen_paths


@pytest.mark.asyncio
async def test_enrich_strips_html_from_status_content() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/v1/accounts/lookup":
            return httpx.Response(200, json=_account())
        return httpx.Response(200, json=[
            _status("1", content="<p>Hello <strong>world</strong></p>"),
        ])
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://mastodon.social/@alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    # No raw HTML tags in any signal summary.
    for s in r.signals:
        assert "<p>" not in s.summary
        assert "<strong>" not in s.summary


@pytest.mark.asyncio
async def test_enrich_unknown_instance_returns_none() -> None:
    handler = lambda req: httpx.Response(200, json=_account())
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://random.example/@alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_lookup_404() -> None:
    handler = lambda req: httpx.Response(404, text="not found")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://mastodon.social/@ghost", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_429() -> None:
    handler = lambda req: httpx.Response(429, text="rate")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://fosstodon.org/@alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_5xx() -> None:
    handler = lambda req: httpx.Response(503, text="bad")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://hachyderm.io/@alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_network_failure() -> None:
    def handler(req): raise httpx.ConnectError("refused", request=req)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://mastodon.social/@alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_caps_signals_at_5() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/v1/accounts/lookup":
            return httpx.Response(200, json=_account())
        return httpx.Response(200, json=[_status(str(i)) for i in range(20)])
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://mastodon.social/@alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None and len(r.signals) <= 5


@pytest.mark.asyncio
async def test_enrich_propagates_low_confidence() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/v1/accounts/lookup":
            return httpx.Response(200, json=_account())
        return httpx.Response(200, json=[_status("1")])
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://mastodon.social/@alice", confidence=0.5)
    r = await p.enrich(hint)
    assert r is not None
    assert r.confidence == 0.5 and r.discovered


def test_known_instances_includes_major_mastodon_servers() -> None:
    assert "mastodon.social" in KNOWN_INSTANCES
    assert "fosstodon.org" in KNOWN_INSTANCES
    assert "hachyderm.io" in KNOWN_INSTANCES
```

- [ ] **Step 2: Run, expect failure**

```bash
uv run pytest tests/unit/test_enrichment_mastodon.py -v
```
Expected: FAIL.

---

### Task 9: Mastodon — implementation

**Files:**
- Create: `src/recruiter/enrichment/mastodon.py`
- Modify: `src/recruiter/enrichment/__init__.py`

- [ ] **Step 1: Implementation**

```python
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import ClassVar
from urllib.parse import urlparse

import httpx

from recruiter.enrichment.provider import (
    EnrichmentHint,
    EnrichmentResult,
    EnrichmentSignal,
    register,
)

logger = logging.getLogger(__name__)

KNOWN_INSTANCES: list[str] = [
    "mastodon.social",
    "fosstodon.org",
    "hachyderm.io",
    "mas.to",
    "infosec.exchange",
    "techhub.social",
    "sigmoid.social",
]

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str) -> str:
    return _HTML_TAG_RE.sub("", s or "").strip()


def _parse_mastodon_url(url: str) -> tuple[str, str] | None:
    """Return (instance, username) for a Mastodon profile URL, or None."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host not in KNOWN_INSTANCES:
        return None
    path = parsed.path.strip("/")
    if not path.startswith("@"):
        return None
    user = path[1:].split("/")[0]
    return (host, user) if user else None


@register("mastodon")
class MastodonProvider:
    name: ClassVar[str] = "mastodon"
    domains: ClassVar[list[str]] = list(KNOWN_INSTANCES)

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        if not hint.url:
            return None
        parsed = _parse_mastodon_url(hint.url)
        if not parsed:
            return None
        instance, username = parsed
        base = f"https://{instance}"

        try:
            lookup = await self._client.get(
                f"{base}/api/v1/accounts/lookup", params={"acct": username}
            )
        except httpx.HTTPError as exc:
            logger.info("mastodon lookup failed for %s@%s: %s", username, instance, exc)
            return None
        if lookup.status_code != 200:
            logger.info("mastodon lookup %s for %s@%s", lookup.status_code, username, instance)
            return None
        try:
            account = lookup.json()
        except ValueError:
            return None
        acct_id = account.get("id")
        if not acct_id:
            return None

        try:
            statuses = await self._client.get(
                f"{base}/api/v1/accounts/{acct_id}/statuses", params={"limit": 5}
            )
        except httpx.HTTPError as exc:
            logger.info("mastodon statuses failed for %s: %s", acct_id, exc)
            return None
        if statuses.status_code != 200:
            return None
        try:
            posts = statuses.json() or []
        except ValueError:
            return None

        signals: list[EnrichmentSignal] = []
        note = _strip_html(account.get("note") or "")
        if note:
            signals.append(EnrichmentSignal(
                type="profile",
                summary=f"Mastodon bio: {note[:200]}",
                url=account.get("url"),
            ))
        for s in posts[:4]:
            content = _strip_html(s.get("content") or "")[:160]
            ts = s.get("created_at")
            try:
                ts_parsed = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
            except (ValueError, AttributeError):
                ts_parsed = None
            signals.append(EnrichmentSignal(
                type="post",
                summary=f"@{username}@{instance}: {content}",
                url=s.get("url"),
                timestamp=ts_parsed,
            ))

        if not signals:
            return None

        followers = account.get("followers_count", 0)
        st_count = account.get("statuses_count", 0)
        summary = (
            f"Mastodon @{username}@{instance} ({followers} followers, {st_count} posts). "
            + (note[:140] if note else "")
        )
        return EnrichmentResult(
            source="mastodon",
            profile_url=account.get("url") or f"{base}/@{username}",
            confidence=hint.confidence,
            discovered=hint.confidence < 1.0,
            signals=signals[:5],
            summary=summary,
        )
```

- [ ] **Step 2: Wire registration**

Append to `src/recruiter/enrichment/__init__.py`:

```python
from recruiter.enrichment import mastodon as _mastodon  # noqa: F401
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/unit/test_enrichment_mastodon.py -v
```
Expected: all 10 PASS.

- [ ] **Step 4: Commit**

```bash
git add src/recruiter/enrichment/mastodon.py \
        src/recruiter/enrichment/__init__.py \
        tests/unit/test_enrichment_mastodon.py
git commit -m "feat(enrichment): add Mastodon provider"
```

---

### Task 10: Bluesky — failing tests

**Files:**
- Create: `tests/unit/test_enrichment_bluesky.py`

API: `https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor=<handle>` and `app.bsky.feed.getAuthorFeed?actor=<handle>&limit=5`. No key.

- [ ] **Step 1: Write the test file**

```python
import httpx
import pytest

from recruiter.enrichment.bluesky import BlueskyProvider
from recruiter.enrichment.provider import EnrichmentHint


def _make_provider(transport: httpx.MockTransport) -> BlueskyProvider:
    return BlueskyProvider(transport=transport)


def _profile() -> dict:
    return {
        "did": "did:plc:alice",
        "handle": "alice.bsky.social",
        "displayName": "Alice Doe",
        "description": "Rust + Postgres engineer",
        "followersCount": 200,
        "postsCount": 1500,
    }


def _feed(items: list[dict] | None = None) -> dict:
    return {"feed": [{"post": item} for item in (items or [])]}


@pytest.mark.asyncio
async def test_enrich_known_profile_returns_signals() -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        if req.url.path.endswith("getProfile"):
            return httpx.Response(200, json=_profile())
        if req.url.path.endswith("getAuthorFeed"):
            return httpx.Response(200, json=_feed([
                {"uri": "at://did:plc:alice/app.bsky.feed.post/1",
                 "record": {"text": "Just shipped a Rust crate", "createdAt": "2025-04-01T12:00:00Z"},
                 "indexedAt": "2025-04-01T12:00:00Z"},
                {"uri": "at://did:plc:alice/app.bsky.feed.post/2",
                 "record": {"text": "Postgres tip of the day", "createdAt": "2025-04-02T12:00:00Z"},
                 "indexedAt": "2025-04-02T12:00:00Z"},
            ]))
        return httpx.Response(404)

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://bsky.app/profile/alice.bsky.social", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert r.source == "bluesky"
    assert r.profile_url == "https://bsky.app/profile/alice.bsky.social"
    assert r.confidence == 1.0
    assert any("getProfile" in p_ for p_ in paths)
    assert any("getAuthorFeed" in p_ for p_ in paths)
    assert any("Rust" in s.summary for s in r.signals)


@pytest.mark.asyncio
async def test_enrich_returns_none_on_unknown_handle() -> None:
    handler = lambda req: httpx.Response(400, text="Profile not found")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://bsky.app/profile/ghost.bsky.social", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_5xx() -> None:
    handler = lambda req: httpx.Response(503)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://bsky.app/profile/alice.bsky.social", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_429() -> None:
    handler = lambda req: httpx.Response(429)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://bsky.app/profile/alice.bsky.social", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_network_failure() -> None:
    def handler(req): raise httpx.ConnectError("refused", request=req)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://bsky.app/profile/alice.bsky.social", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_handles_empty_feed() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("getProfile"):
            return httpx.Response(200, json=_profile())
        return httpx.Response(200, json=_feed([]))
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://bsky.app/profile/alice.bsky.social", confidence=1.0)
    r = await p.enrich(hint)
    # With empty feed but a real profile, the provider should still emit a
    # profile-only signal.
    assert r is not None
    assert any(s.type == "profile" for s in r.signals)


@pytest.mark.asyncio
async def test_enrich_caps_signals_at_5() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("getProfile"):
            return httpx.Response(200, json=_profile())
        return httpx.Response(200, json=_feed([
            {"uri": f"at://x/{i}",
             "record": {"text": f"post {i}", "createdAt": "2025-01-01T00:00:00Z"},
             "indexedAt": "2025-01-01T00:00:00Z"}
            for i in range(20)
        ]))
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://bsky.app/profile/alice.bsky.social", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None and len(r.signals) <= 5


@pytest.mark.asyncio
async def test_enrich_propagates_low_confidence() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("getProfile"):
            return httpx.Response(200, json=_profile())
        return httpx.Response(200, json=_feed([
            {"uri": "at://x/1", "record": {"text": "x", "createdAt": "2025-01-01T00:00:00Z"},
             "indexedAt": "2025-01-01T00:00:00Z"}
        ]))
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://bsky.app/profile/alice.bsky.social", confidence=0.5)
    r = await p.enrich(hint)
    assert r is not None and r.confidence == 0.5 and r.discovered


@pytest.mark.asyncio
async def test_enrich_with_name_only_hint_returns_none() -> None:
    handler = lambda req: httpx.Response(200, json={})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(name="Alice Doe", confidence=0.5)
    assert await p.enrich(hint) is None
```

---

### Task 11: Bluesky — implementation

**Files:**
- Create: `src/recruiter/enrichment/bluesky.py`
- Modify: `src/recruiter/enrichment/__init__.py`

- [ ] **Step 1: Implementation**

```python
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import ClassVar

import httpx

from recruiter.enrichment.provider import (
    EnrichmentHint,
    EnrichmentResult,
    EnrichmentSignal,
    register,
)

logger = logging.getLogger(__name__)

BSKY_BASE = "https://public.api.bsky.app/xrpc"


def _handle_from_url(url: str) -> str | None:
    m = re.search(r"bsky\.app/profile/([A-Za-z0-9._:-]+)", url or "")
    return m.group(1) if m else None


@register("bluesky")
class BlueskyProvider:
    name: ClassVar[str] = "bluesky"
    domains: ClassVar[list[str]] = ["bsky.app"]

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        handle = _handle_from_url(hint.url) if hint.url else None
        if not handle:
            return None
        try:
            prof = await self._client.get(
                f"{BSKY_BASE}/app.bsky.actor.getProfile", params={"actor": handle}
            )
        except httpx.HTTPError as exc:
            logger.info("bluesky getProfile failed for %s: %s", handle, exc)
            return None
        if prof.status_code != 200:
            logger.info("bluesky getProfile %s for %s", prof.status_code, handle)
            return None
        try:
            profile = prof.json()
        except ValueError:
            return None

        try:
            feed_resp = await self._client.get(
                f"{BSKY_BASE}/app.bsky.feed.getAuthorFeed",
                params={"actor": handle, "limit": 5},
            )
        except httpx.HTTPError as exc:
            logger.info("bluesky getAuthorFeed failed for %s: %s", handle, exc)
            return None
        if feed_resp.status_code != 200:
            return None
        try:
            feed = feed_resp.json().get("feed") or []
        except ValueError:
            return None

        signals: list[EnrichmentSignal] = []
        desc = profile.get("description")
        if desc:
            signals.append(EnrichmentSignal(
                type="profile",
                summary=f"Bluesky bio: {desc[:200]}",
                url=f"https://bsky.app/profile/{handle}",
            ))
        for item in feed[:4]:
            post = item.get("post") or {}
            rec = post.get("record") or {}
            text = (rec.get("text") or "")[:160]
            uri = post.get("uri") or ""
            ts = rec.get("createdAt") or post.get("indexedAt")
            try:
                ts_parsed = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
            except (ValueError, AttributeError):
                ts_parsed = None
            # AT-URI → web URL: at://<did>/app.bsky.feed.post/<rkey> →
            # https://bsky.app/profile/<handle>/post/<rkey>
            web_url = None
            m = re.search(r"app\.bsky\.feed\.post/([A-Za-z0-9]+)$", uri)
            if m:
                web_url = f"https://bsky.app/profile/{handle}/post/{m.group(1)}"
            signals.append(EnrichmentSignal(
                type="post",
                summary=f"@{handle}: {text}",
                url=web_url,
                timestamp=ts_parsed,
            ))

        if not signals:
            return None

        followers = profile.get("followersCount", 0)
        posts = profile.get("postsCount", 0)
        summary = (
            f"Bluesky @{handle} ({followers} followers, {posts} posts). "
            + ((desc or "")[:140])
        )
        return EnrichmentResult(
            source="bluesky",
            profile_url=f"https://bsky.app/profile/{handle}",
            confidence=hint.confidence,
            discovered=hint.confidence < 1.0,
            signals=signals[:5],
            summary=summary,
        )
```

- [ ] **Step 2: Wire registration**

Append `from recruiter.enrichment import bluesky as _bluesky  # noqa: F401` to `src/recruiter/enrichment/__init__.py`.

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/unit/test_enrichment_bluesky.py -v
```
Expected: all 9 PASS.

- [ ] **Step 4: Commit**

```bash
git add src/recruiter/enrichment/bluesky.py \
        src/recruiter/enrichment/__init__.py \
        tests/unit/test_enrichment_bluesky.py
git commit -m "feat(enrichment): add Bluesky provider"
```

---

### Task 12: Dev.to — failing tests

**Files:**
- Create: `tests/unit/test_enrichment_devto.py`

API: `https://dev.to/api/users/by_username?url=<u>` → user object; `https://dev.to/api/articles?username=<u>&per_page=5` → recent posts. No key.

- [ ] **Step 1: Write the test file**

```python
import httpx
import pytest

from recruiter.enrichment.devto import DevToProvider
from recruiter.enrichment.provider import EnrichmentHint


def _make_provider(transport: httpx.MockTransport) -> DevToProvider:
    return DevToProvider(transport=transport)


def _user() -> dict:
    return {
        "username": "alice",
        "name": "Alice Doe",
        "summary": "Rust developer",
        "website_url": "https://alice.dev",
        "twitter_username": "alice",
        "github_username": "alice",
    }


def _articles(n: int = 2) -> list[dict]:
    return [
        {
            "id": i + 1,
            "title": f"Async Rust tip #{i+1}",
            "url": f"https://dev.to/alice/async-rust-tip-{i+1}",
            "published_at": "2025-04-01T00:00:00Z",
            "tag_list": ["rust", "async"],
            "positive_reactions_count": 10 + i,
        }
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_enrich_known_user_returns_signals() -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        if req.url.path == "/api/users/by_username":
            return httpx.Response(200, json=_user())
        if req.url.path == "/api/articles":
            return httpx.Response(200, json=_articles(3))
        return httpx.Response(404)

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://dev.to/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert r.source == "devto"
    assert r.profile_url == "https://dev.to/alice"
    assert r.confidence == 1.0
    assert any("Async Rust" in s.summary for s in r.signals)


@pytest.mark.asyncio
async def test_enrich_user_not_found_returns_none() -> None:
    handler = lambda req: httpx.Response(404, text="not found")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://dev.to/ghost", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_handles_no_articles() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/users/by_username":
            return httpx.Response(200, json=_user())
        return httpx.Response(200, json=[])
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://dev.to/alice", confidence=1.0)
    r = await p.enrich(hint)
    # No articles but a real profile → still emits a profile-only signal.
    assert r is not None
    assert any(s.type == "profile" for s in r.signals)


@pytest.mark.asyncio
async def test_enrich_returns_none_on_5xx() -> None:
    handler = lambda req: httpx.Response(503)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://dev.to/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_429() -> None:
    handler = lambda req: httpx.Response(429)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://dev.to/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_network_failure() -> None:
    def handler(req): raise httpx.ConnectError("refused", request=req)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://dev.to/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_caps_signals_at_5() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/users/by_username":
            return httpx.Response(200, json=_user())
        return httpx.Response(200, json=_articles(20))
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://dev.to/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None and len(r.signals) <= 5


@pytest.mark.asyncio
async def test_enrich_propagates_low_confidence() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/users/by_username":
            return httpx.Response(200, json=_user())
        return httpx.Response(200, json=_articles(2))
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://dev.to/alice", confidence=0.5)
    r = await p.enrich(hint)
    assert r is not None and r.confidence == 0.5 and r.discovered


@pytest.mark.asyncio
async def test_enrich_with_name_only_hint_returns_none() -> None:
    handler = lambda req: httpx.Response(200, json={})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(name="Alice Doe", confidence=0.5)
    assert await p.enrich(hint) is None
```

---

### Task 13: Dev.to — implementation

**Files:**
- Create: `src/recruiter/enrichment/devto.py`
- Modify: `src/recruiter/enrichment/__init__.py`

```python
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import ClassVar

import httpx

from recruiter.enrichment.provider import (
    EnrichmentHint,
    EnrichmentResult,
    EnrichmentSignal,
    register,
)

logger = logging.getLogger(__name__)


def _username_from_devto_url(url: str) -> str | None:
    m = re.match(r"https?://dev\.to/([A-Za-z0-9_-]+)/?", url or "")
    return m.group(1) if m else None


@register("devto")
class DevToProvider:
    name: ClassVar[str] = "devto"
    domains: ClassVar[list[str]] = ["dev.to"]

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        username = _username_from_devto_url(hint.url) if hint.url else None
        if not username:
            return None

        base = "https://dev.to"
        try:
            user_r = await self._client.get(
                f"{base}/api/users/by_username", params={"url": username}
            )
            arts_r = await self._client.get(
                f"{base}/api/articles", params={"username": username, "per_page": 5}
            )
        except httpx.HTTPError as exc:
            logger.info("devto fetch failed for %s: %s", username, exc)
            return None
        if user_r.status_code != 200 or arts_r.status_code != 200:
            return None
        try:
            user = user_r.json()
            articles = arts_r.json() or []
        except ValueError:
            return None

        signals: list[EnrichmentSignal] = []
        bio = user.get("summary") or ""
        gh = user.get("github_username")
        site = user.get("website_url")
        bio_extra = []
        if gh:
            bio_extra.append(f"github.com/{gh}")
        if site:
            bio_extra.append(site)
        if bio or bio_extra:
            signals.append(EnrichmentSignal(
                type="profile",
                summary=f"Dev.to: {bio} {' '.join(bio_extra)}".strip(),
                url=f"{base}/{username}",
            ))
        for art in articles[:4]:
            ts = art.get("published_at")
            try:
                ts_parsed = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
            except (ValueError, AttributeError):
                ts_parsed = None
            tags = ", ".join(art.get("tag_list") or [])
            signals.append(EnrichmentSignal(
                type="writing",
                summary=f"Dev.to article: \"{art.get('title')}\""
                        + (f" [{tags}]" if tags else "")
                        + f" — {art.get('positive_reactions_count', 0)} reactions",
                url=art.get("url"),
                timestamp=ts_parsed,
            ))

        if not signals:
            return None

        summary = f"Dev.to author {username}; {len(articles)} recent posts."
        return EnrichmentResult(
            source="devto",
            profile_url=f"{base}/{username}",
            confidence=hint.confidence,
            discovered=hint.confidence < 1.0,
            signals=signals[:5],
            summary=summary,
        )
```

- [ ] **Step 2: Wire registration + run tests + commit**

Append to `__init__.py`: `from recruiter.enrichment import devto as _devto  # noqa: F401`.

```bash
uv run pytest tests/unit/test_enrichment_devto.py -v
```
Expected: all 9 PASS. Then commit: `feat(enrichment): add Dev.to provider`.

---

### Task 14: Stack Overflow — failing tests

**Files:**
- Create: `tests/unit/test_enrichment_stackoverflow.py`

API: Stack Exchange API v2.3. `https://api.stackexchange.com/2.3/users?inname=<name>&site=stackoverflow` for discovery; for known URL `/u/<id>/<slug>`, fetch `/users/{id}?site=stackoverflow` and `/users/{id}/answers?site=stackoverflow&pagesize=5&sort=votes`. Optional API key bumps quota.

- [ ] **Step 1: Write the test file**

```python
import httpx
import pytest

from recruiter.enrichment.provider import EnrichmentHint
from recruiter.enrichment.stackoverflow import StackOverflowProvider


def _make_provider(transport: httpx.MockTransport, **kw) -> StackOverflowProvider:
    return StackOverflowProvider(transport=transport, **kw)


def _user_resp() -> dict:
    return {
        "items": [{
            "user_id": 12345,
            "display_name": "Alice Doe",
            "reputation": 5400,
            "link": "https://stackoverflow.com/users/12345/alice-doe",
            "about_me": "<p>Rust dev</p>",
        }]
    }


def _answers_resp() -> dict:
    return {
        "items": [
            {
                "answer_id": 1, "question_id": 100,
                "score": 25, "is_accepted": True,
                "creation_date": 1700000000,
                "tags": ["rust", "async"],
                "link": "https://stackoverflow.com/a/1",
            },
            {
                "answer_id": 2, "question_id": 101,
                "score": 8, "is_accepted": False,
                "creation_date": 1701000000,
                "link": "https://stackoverflow.com/a/2",
            },
        ]
    }


@pytest.mark.asyncio
async def test_enrich_known_user_returns_signals() -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        if "/users/12345/answers" in req.url.path:
            return httpx.Response(200, json=_answers_resp())
        if "/users/12345" in req.url.path:
            return httpx.Response(200, json=_user_resp())
        return httpx.Response(404)

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://stackoverflow.com/users/12345/alice-doe", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert r.source == "stackoverflow"
    assert r.profile_url == "https://stackoverflow.com/users/12345/alice-doe"
    assert any(s.type == "answer" for s in r.signals)
    assert any("rep" in r.summary.lower() or "reputation" in r.summary.lower() for _ in [0])


@pytest.mark.asyncio
async def test_enrich_passes_api_key_when_provided() -> None:
    seen_params: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_params.append(dict(req.url.params))
        if "/users/12345/answers" in req.url.path:
            return httpx.Response(200, json={"items": []})
        return httpx.Response(200, json=_user_resp())

    p = _make_provider(httpx.MockTransport(handler), api_key="test-key")
    hint = EnrichmentHint(url="https://stackoverflow.com/users/12345/alice", confidence=1.0)
    await p.enrich(hint)
    # Both requests should include the key.
    for params in seen_params:
        assert params.get("key") == "test-key"


@pytest.mark.asyncio
async def test_enrich_user_not_found_returns_none() -> None:
    handler = lambda req: httpx.Response(200, json={"items": []})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://stackoverflow.com/users/99999/ghost", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_404() -> None:
    handler = lambda req: httpx.Response(404)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://stackoverflow.com/users/12345/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_429() -> None:
    handler = lambda req: httpx.Response(429)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://stackoverflow.com/users/12345/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_5xx() -> None:
    handler = lambda req: httpx.Response(503)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://stackoverflow.com/users/12345/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_network_failure() -> None:
    def handler(req): raise httpx.ConnectError("refused", request=req)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://stackoverflow.com/users/12345/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_caps_signals_at_5() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/answers" in req.url.path:
            return httpx.Response(200, json={
                "items": [
                    {"answer_id": i, "question_id": i+1000, "score": 1,
                     "is_accepted": False, "creation_date": 1700000000,
                     "link": f"https://stackoverflow.com/a/{i}"}
                    for i in range(20)
                ]
            })
        return httpx.Response(200, json=_user_resp())
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://stackoverflow.com/users/12345/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None and len(r.signals) <= 5


@pytest.mark.asyncio
async def test_enrich_propagates_low_confidence() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/answers" in req.url.path:
            return httpx.Response(200, json=_answers_resp())
        return httpx.Response(200, json=_user_resp())
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://stackoverflow.com/users/12345/alice", confidence=0.5)
    r = await p.enrich(hint)
    assert r is not None and r.confidence == 0.5 and r.discovered


@pytest.mark.asyncio
async def test_enrich_with_name_only_hint_returns_none() -> None:
    handler = lambda req: httpx.Response(200, json={"items": []})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(name="Alice Doe", confidence=0.5)
    # Without a URL the SO provider has no path forward; discovery passes
    # URLs not bare names.
    assert await p.enrich(hint) is None
```

---

### Task 15: Stack Overflow — implementation

**Files:**
- Create: `src/recruiter/enrichment/stackoverflow.py`
- Modify: `src/recruiter/enrichment/__init__.py`

```python
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import ClassVar

import httpx

from recruiter.enrichment.provider import (
    EnrichmentHint,
    EnrichmentResult,
    EnrichmentSignal,
    register,
)

logger = logging.getLogger(__name__)

SE_BASE = "https://api.stackexchange.com/2.3"


def _user_id_from_url(url: str) -> str | None:
    m = re.search(r"stackoverflow\.com/users/(\d+)", url or "")
    return m.group(1) if m else None


@register("stackoverflow")
class StackOverflowProvider:
    name: ClassVar[str] = "stackoverflow"
    domains: ClassVar[list[str]] = ["stackoverflow.com", "stackexchange.com"]

    def __init__(
        self,
        *,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _params(self, **extra) -> dict:
        out = {"site": "stackoverflow", **extra}
        if self._api_key:
            out["key"] = self._api_key
        return out

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        user_id = _user_id_from_url(hint.url) if hint.url else None
        if not user_id:
            return None

        try:
            user_r = await self._client.get(
                f"{SE_BASE}/users/{user_id}", params=self._params()
            )
            ans_r = await self._client.get(
                f"{SE_BASE}/users/{user_id}/answers",
                params=self._params(pagesize=5, sort="votes", order="desc"),
            )
        except httpx.HTTPError as exc:
            logger.info("stackoverflow fetch failed for %s: %s", user_id, exc)
            return None
        if user_r.status_code != 200 or ans_r.status_code != 200:
            return None
        try:
            users = user_r.json().get("items") or []
            answers = ans_r.json().get("items") or []
        except ValueError:
            return None
        if not users:
            return None

        u = users[0]
        rep = u.get("reputation", 0)
        link = u.get("link") or hint.url
        signals: list[EnrichmentSignal] = []
        signals.append(EnrichmentSignal(
            type="profile",
            summary=f"Stack Overflow: {rep} reputation as {u.get('display_name','user')}",
            url=link,
        ))
        for a in answers[:4]:
            ts = a.get("creation_date")
            ts_parsed = datetime.fromtimestamp(ts, tz=timezone.utc) if isinstance(ts, (int, float)) else None
            tags = ", ".join(a.get("tags") or [])
            accepted = "[accepted] " if a.get("is_accepted") else ""
            signals.append(EnrichmentSignal(
                type="answer",
                summary=f"{accepted}SO answer ({a.get('score',0)} votes)"
                        + (f" tags: {tags}" if tags else ""),
                url=a.get("link"),
                timestamp=ts_parsed,
            ))

        summary = (
            f"Stack Overflow: {rep} rep, {len(answers)} top-voted answers shown."
        )
        return EnrichmentResult(
            source="stackoverflow",
            profile_url=link,
            confidence=hint.confidence,
            discovered=hint.confidence < 1.0,
            signals=signals[:5],
            summary=summary,
        )
```

- [ ] **Step 2: Wire registration + tests + commit**

Append to `__init__.py`: `from recruiter.enrichment import stackoverflow as _stackoverflow  # noqa: F401`.

```bash
uv run pytest tests/unit/test_enrichment_stackoverflow.py -v
```
Expected: all 10 PASS. Commit: `feat(enrichment): add Stack Overflow provider`.

---

### Task 16: GitHub enrichment — failing tests

**Files:**
- Create: `tests/unit/test_enrichment_github.py`

> **Important:** the existing `src/recruiter/sourcing/github.py` is the *search engine* (calls `/search/users`). This new module is a *per-user enrichment fetcher* that hits `/users/{u}` and `/users/{u}/repos` to summarize a known candidate. The two share the existing `github_token_enc` setting.

API: REST `/users/{u}`, `/users/{u}/repos?per_page=5&sort=updated`. GraphQL contributions calendar (optional, for the totals — keep behind a try/except so a missing scope doesn't break the path). Bearer token optional.

- [ ] **Step 1: Write the test file**

```python
import httpx
import pytest

from recruiter.enrichment.github import GitHubEnrichmentProvider
from recruiter.enrichment.provider import EnrichmentHint


def _make_provider(transport: httpx.MockTransport, **kw) -> GitHubEnrichmentProvider:
    return GitHubEnrichmentProvider(transport=transport, **kw)


def _user_resp() -> dict:
    return {
        "login": "alice",
        "name": "Alice Doe",
        "bio": "Rust + async",
        "public_repos": 42,
        "followers": 200,
        "html_url": "https://github.com/alice",
        "blog": "https://alice.dev",
        "company": "Acme",
        "email": "alice@acme.com",
    }


def _repos_resp() -> list[dict]:
    return [
        {"name": "rust-helper", "html_url": "https://github.com/alice/rust-helper",
         "stargazers_count": 120, "language": "Rust",
         "description": "async helpers", "pushed_at": "2025-04-01T12:00:00Z"},
        {"name": "pg-tools", "html_url": "https://github.com/alice/pg-tools",
         "stargazers_count": 30, "language": "Python",
         "description": "Postgres tools", "pushed_at": "2025-03-01T12:00:00Z"},
    ]


@pytest.mark.asyncio
async def test_enrich_known_user_returns_signals() -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        if req.url.path == "/users/alice":
            return httpx.Response(200, json=_user_resp())
        if req.url.path == "/users/alice/repos":
            return httpx.Response(200, json=_repos_resp())
        return httpx.Response(404)

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://github.com/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert r.source == "github"
    assert r.profile_url == "https://github.com/alice"
    assert r.confidence == 1.0
    assert any("rust-helper" in s.summary for s in r.signals)


@pytest.mark.asyncio
async def test_enrich_passes_bearer_token_when_provided() -> None:
    seen_auth: list[str | None] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_auth.append(req.headers.get("Authorization"))
        if req.url.path == "/users/alice":
            return httpx.Response(200, json=_user_resp())
        return httpx.Response(200, json=[])

    p = _make_provider(httpx.MockTransport(handler), token="ghp_xxx")
    hint = EnrichmentHint(url="https://github.com/alice", confidence=1.0)
    await p.enrich(hint)
    assert all(a == "Bearer ghp_xxx" for a in seen_auth if a)


@pytest.mark.asyncio
async def test_enrich_returns_none_on_404() -> None:
    handler = lambda req: httpx.Response(404, json={"message": "Not Found"})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://github.com/ghost", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_401() -> None:
    handler = lambda req: httpx.Response(401, json={"message": "Bad credentials"})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://github.com/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_403_rate_limit() -> None:
    handler = lambda req: httpx.Response(403, json={"message": "rate limit"})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://github.com/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_5xx() -> None:
    handler = lambda req: httpx.Response(503)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://github.com/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_network_failure() -> None:
    def handler(req): raise httpx.ConnectError("refused", request=req)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://github.com/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_caps_signals_at_5() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/users/alice":
            return httpx.Response(200, json=_user_resp())
        return httpx.Response(200, json=[
            {"name": f"r{i}", "html_url": f"https://github.com/alice/r{i}",
             "stargazers_count": i, "language": "Python", "description": "x",
             "pushed_at": "2025-01-01T00:00:00Z"}
            for i in range(20)
        ])
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://github.com/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None and len(r.signals) <= 5


@pytest.mark.asyncio
async def test_enrich_emits_email_signal_when_user_has_public_email() -> None:
    """The user's public email should appear in a signal so the identity
    engine can match it against the candidate's anchor email."""
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/users/alice":
            return httpx.Response(200, json=_user_resp())
        return httpx.Response(200, json=[])
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://github.com/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert any("alice@acme.com" in s.summary for s in r.signals)


@pytest.mark.asyncio
async def test_enrich_propagates_low_confidence() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/users/alice":
            return httpx.Response(200, json=_user_resp())
        return httpx.Response(200, json=_repos_resp())
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://github.com/alice", confidence=0.5)
    r = await p.enrich(hint)
    assert r is not None and r.confidence == 0.5 and r.discovered
```

---

### Task 17: GitHub enrichment — implementation

**Files:**
- Create: `src/recruiter/enrichment/github.py`
- Modify: `src/recruiter/enrichment/__init__.py`

```python
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import ClassVar

import httpx

from recruiter.enrichment.provider import (
    EnrichmentHint,
    EnrichmentResult,
    EnrichmentSignal,
    register,
)

logger = logging.getLogger(__name__)

GH_BASE = "https://api.github.com"


def _username_from_gh_url(url: str) -> str | None:
    m = re.match(r"https?://github\.com/([A-Za-z0-9_-]+)/?$", (url or "").rstrip("/"))
    return m.group(1) if m else None


@register("github")
class GitHubEnrichmentProvider:
    """Per-user enrichment fetcher. Distinct from `recruiter.sourcing.github`,
    which is a search engine. Reuses the same `github_token_enc` setting."""

    name: ClassVar[str] = "github"
    domains: ClassVar[list[str]] = ["github.com"]

    def __init__(
        self,
        *,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = token
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/vnd.github+json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        username = _username_from_gh_url(hint.url) if hint.url else None
        if not username:
            return None

        try:
            user_r = await self._client.get(
                f"{GH_BASE}/users/{username}", headers=self._headers()
            )
            repo_r = await self._client.get(
                f"{GH_BASE}/users/{username}/repos",
                headers=self._headers(),
                params={"per_page": 5, "sort": "updated"},
            )
        except httpx.HTTPError as exc:
            logger.info("github enrichment failed for %s: %s", username, exc)
            return None
        if user_r.status_code != 200 or repo_r.status_code != 200:
            logger.info(
                "github enrichment status %s/%s for %s",
                user_r.status_code, repo_r.status_code, username,
            )
            return None
        try:
            user = user_r.json()
            repos = repo_r.json() or []
        except ValueError:
            return None

        signals: list[EnrichmentSignal] = []
        bio = user.get("bio") or ""
        company = user.get("company") or ""
        email = user.get("email") or ""
        blog = user.get("blog") or ""
        prof_extra = " ".join(p for p in [company, email, blog] if p)
        signals.append(EnrichmentSignal(
            type="profile",
            summary=f"GitHub @{username}: {user.get('public_repos',0)} repos, "
                    f"{user.get('followers',0)} followers"
                    + (f". Bio: {bio}" if bio else "")
                    + (f". {prof_extra}" if prof_extra else ""),
            url=user.get("html_url") or f"https://github.com/{username}",
        ))
        for repo in repos[:4]:
            ts = repo.get("pushed_at")
            try:
                ts_parsed = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
            except (ValueError, AttributeError):
                ts_parsed = None
            lang = repo.get("language") or "Other"
            stars = repo.get("stargazers_count", 0)
            desc = repo.get("description") or ""
            signals.append(EnrichmentSignal(
                type="code",
                summary=f"{repo.get('name')} [{lang}, {stars} stars]"
                        + (f": {desc[:120]}" if desc else ""),
                url=repo.get("html_url"),
                timestamp=ts_parsed,
            ))

        summary = (
            f"GitHub @{username}: {user.get('public_repos',0)} public repos, "
            f"{user.get('followers',0)} followers."
        )
        return EnrichmentResult(
            source="github",
            profile_url=user.get("html_url") or f"https://github.com/{username}",
            confidence=hint.confidence,
            discovered=hint.confidence < 1.0,
            signals=signals[:5],
            summary=summary,
        )
```

> **Decision (in-plan):** the GraphQL contributions-calendar query mentioned in the spec is **deferred** — it requires a token with `read:user` scope, which the existing `github_token_enc` may not have. The REST `public_repos` / `followers` numbers are sufficient for v1; we can layer the contributions count on later without changing the schema.

- [ ] **Step 2: Wire registration + tests + commit**

Append to `__init__.py`: `from recruiter.enrichment import github as _github  # noqa: F401`.

```bash
uv run pytest tests/unit/test_enrichment_github.py -v
```
Expected: all 10 PASS. Commit: `feat(enrichment): add GitHub per-user enrichment provider`.

---

### Task 18: YouTube — failing tests

**Files:**
- Create: `tests/unit/test_enrichment_youtube.py`

API: YouTube Data API v3. `https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&forHandle=@<u>&key=<key>` then `https://www.googleapis.com/youtube/v3/search?part=snippet&channelId=<id>&maxResults=5&order=date&type=video&key=<key>`. Requires `enrichment_youtube_api_key_enc`.

- [ ] **Step 1: Write the test file**

```python
import httpx
import pytest

from recruiter.enrichment.provider import EnrichmentHint
from recruiter.enrichment.youtube import YouTubeProvider


def _make_provider(transport: httpx.MockTransport, **kw) -> YouTubeProvider:
    return YouTubeProvider(api_key="ytkey", transport=transport, **kw)


def _channels(channel_id: str = "UC123") -> dict:
    return {
        "items": [{
            "id": channel_id,
            "snippet": {
                "title": "Alice's Channel",
                "description": "Rust talks",
                "customUrl": "@alice",
            },
            "statistics": {
                "subscriberCount": "1500",
                "videoCount": "12",
            },
        }]
    }


def _videos() -> dict:
    return {
        "items": [
            {
                "id": {"videoId": "vid1"},
                "snippet": {
                    "title": "RustConf talk: async lifetimes",
                    "publishedAt": "2025-04-01T12:00:00Z",
                    "description": "Talk at RustConf 2025",
                },
            },
            {
                "id": {"videoId": "vid2"},
                "snippet": {
                    "title": "Postgres internals",
                    "publishedAt": "2025-03-01T12:00:00Z",
                    "description": "Internal architecture",
                },
            },
        ]
    }


@pytest.mark.asyncio
async def test_enrich_known_channel_returns_signals() -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        if req.url.path.endswith("/channels"):
            return httpx.Response(200, json=_channels())
        if req.url.path.endswith("/search"):
            return httpx.Response(200, json=_videos())
        return httpx.Response(404)

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.youtube.com/@alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert r.source == "youtube"
    assert r.confidence == 1.0
    assert "@alice" in r.profile_url
    assert any("RustConf" in s.summary for s in r.signals)
    assert any(s.type == "talk" for s in r.signals)


@pytest.mark.asyncio
async def test_enrich_passes_api_key_in_query() -> None:
    seen_keys: list[str | None] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_keys.append(req.url.params.get("key"))
        if req.url.path.endswith("/channels"):
            return httpx.Response(200, json=_channels())
        return httpx.Response(200, json=_videos())

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.youtube.com/@alice", confidence=1.0)
    await p.enrich(hint)
    assert all(k == "ytkey" for k in seen_keys)


@pytest.mark.asyncio
async def test_enrich_unknown_handle_returns_none() -> None:
    handler = lambda req: httpx.Response(200, json={"items": []})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.youtube.com/@ghost", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_403_quota() -> None:
    handler = lambda req: httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.youtube.com/@alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_400_invalid_key() -> None:
    handler = lambda req: httpx.Response(400, json={"error": {"errors": [{"reason": "keyInvalid"}]}})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.youtube.com/@alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_429() -> None:
    handler = lambda req: httpx.Response(429)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.youtube.com/@alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_5xx() -> None:
    handler = lambda req: httpx.Response(503)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.youtube.com/@alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_network_failure() -> None:
    def handler(req): raise httpx.ConnectError("refused", request=req)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.youtube.com/@alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_caps_signals_at_5() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/channels"):
            return httpx.Response(200, json=_channels())
        return httpx.Response(200, json={
            "items": [
                {"id": {"videoId": f"v{i}"},
                 "snippet": {"title": f"video {i}", "publishedAt": "2025-01-01T00:00:00Z",
                             "description": "x"}}
                for i in range(20)
            ]
        })
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.youtube.com/@alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None and len(r.signals) <= 5


@pytest.mark.asyncio
async def test_enrich_propagates_low_confidence() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/channels"):
            return httpx.Response(200, json=_channels())
        return httpx.Response(200, json=_videos())
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://www.youtube.com/@alice", confidence=0.5)
    r = await p.enrich(hint)
    assert r is not None and r.confidence == 0.5 and r.discovered
```

---

### Task 19: YouTube — implementation

**Files:**
- Create: `src/recruiter/enrichment/youtube.py`
- Modify: `src/recruiter/enrichment/__init__.py`

```python
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import ClassVar

import httpx

from recruiter.enrichment.provider import (
    EnrichmentHint,
    EnrichmentResult,
    EnrichmentSignal,
    register,
)

logger = logging.getLogger(__name__)

YT_BASE = "https://www.googleapis.com/youtube/v3"


def _handle_from_url(url: str) -> str | None:
    m = re.search(r"youtube\.com/(@[A-Za-z0-9._-]+)", url or "")
    return m.group(1) if m else None


@register("youtube")
class YouTubeProvider:
    name: ClassVar[str] = "youtube"
    domains: ClassVar[list[str]] = ["youtube.com", "www.youtube.com"]

    def __init__(
        self,
        *,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        handle = _handle_from_url(hint.url) if hint.url else None
        if not handle:
            return None

        try:
            ch_r = await self._client.get(
                f"{YT_BASE}/channels",
                params={
                    "part": "snippet,statistics",
                    "forHandle": handle,
                    "key": self._api_key,
                },
            )
        except httpx.HTTPError as exc:
            logger.info("youtube channels failed for %s: %s", handle, exc)
            return None
        if ch_r.status_code != 200:
            return None
        try:
            items = ch_r.json().get("items") or []
        except ValueError:
            return None
        if not items:
            return None

        ch = items[0]
        channel_id = ch.get("id")
        snip = ch.get("snippet") or {}
        stats = ch.get("statistics") or {}

        try:
            sr_r = await self._client.get(
                f"{YT_BASE}/search",
                params={
                    "part": "snippet",
                    "channelId": channel_id,
                    "maxResults": 5,
                    "order": "date",
                    "type": "video",
                    "key": self._api_key,
                },
            )
        except httpx.HTTPError as exc:
            logger.info("youtube search failed for %s: %s", channel_id, exc)
            return None
        if sr_r.status_code != 200:
            return None
        try:
            videos = sr_r.json().get("items") or []
        except ValueError:
            return None

        signals: list[EnrichmentSignal] = []
        signals.append(EnrichmentSignal(
            type="profile",
            summary=f"YouTube channel {snip.get('title','')}: "
                    f"{stats.get('subscriberCount','?')} subscribers, "
                    f"{stats.get('videoCount','?')} videos."
                    + (f" {snip.get('description','')[:140]}" if snip.get("description") else ""),
            url=f"https://www.youtube.com/{handle}",
        ))
        for v in videos[:4]:
            vsnip = v.get("snippet") or {}
            vid = (v.get("id") or {}).get("videoId")
            ts = vsnip.get("publishedAt")
            try:
                ts_parsed = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
            except (ValueError, AttributeError):
                ts_parsed = None
            signals.append(EnrichmentSignal(
                type="talk",
                summary=f"YouTube: \"{vsnip.get('title','')}\""
                        + (f" — {vsnip.get('description','')[:120]}" if vsnip.get("description") else ""),
                url=f"https://www.youtube.com/watch?v={vid}" if vid else None,
                timestamp=ts_parsed,
            ))

        summary = (
            f"YouTube channel {snip.get('title','')} ({handle}): "
            f"{stats.get('subscriberCount','?')} subs."
        )
        return EnrichmentResult(
            source="youtube",
            profile_url=f"https://www.youtube.com/{handle}",
            confidence=hint.confidence,
            discovered=hint.confidence < 1.0,
            signals=signals[:5],
            summary=summary,
        )
```

- [ ] **Step 2: Wire registration + tests + commit**

Append to `__init__.py`: `from recruiter.enrichment import youtube as _youtube  # noqa: F401`.

```bash
uv run pytest tests/unit/test_enrichment_youtube.py -v
```
Expected: all 9 PASS. Commit: `feat(enrichment): add YouTube provider`.

---

### Task 20: Twitter/X — failing tests

**Files:**
- Create: `tests/unit/test_enrichment_twitter.py`

API: X API v2 Basic. `GET https://api.twitter.com/2/users/by/username/<u>` then `GET /2/users/<id>/tweets?max_results=5&tweet.fields=created_at,public_metrics`. Bearer-token auth.

> **Risk note:** the X API v2 has historically been the *least* stable interface in this set. The Basic tier is paid ($200/mo), so most CI runs hit auth/quota errors. Tests rely entirely on `httpx.MockTransport`; no real network calls.

- [ ] **Step 1: Write the test file**

```python
import httpx
import pytest

from recruiter.enrichment.provider import EnrichmentHint
from recruiter.enrichment.twitter import TwitterProvider


def _make_provider(transport: httpx.MockTransport, **kw) -> TwitterProvider:
    return TwitterProvider(bearer_token="bearer-xxx", transport=transport, **kw)


def _user(uid: str = "777") -> dict:
    return {
        "data": {
            "id": uid,
            "username": "alice",
            "name": "Alice Doe",
            "description": "Rust + Postgres",
            "public_metrics": {"followers_count": 5000, "tweet_count": 4321},
            "url": "https://alice.dev",
        }
    }


def _tweets() -> dict:
    return {
        "data": [
            {"id": "t1", "text": "Just shipped a Rust crate.",
             "created_at": "2025-04-01T12:00:00.000Z",
             "public_metrics": {"like_count": 100, "retweet_count": 20, "reply_count": 5, "quote_count": 1}},
            {"id": "t2", "text": "Postgres tip: covering indexes.",
             "created_at": "2025-04-02T12:00:00.000Z",
             "public_metrics": {"like_count": 40, "retweet_count": 8, "reply_count": 2, "quote_count": 0}},
        ]
    }


@pytest.mark.asyncio
async def test_enrich_known_user_returns_signals() -> None:
    seen_auth: list[str | None] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_auth.append(req.headers.get("Authorization"))
        if "/users/by/username/" in req.url.path:
            return httpx.Response(200, json=_user())
        if "/users/777/tweets" in req.url.path:
            return httpx.Response(200, json=_tweets())
        return httpx.Response(404)

    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://twitter.com/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert r.source == "twitter"
    assert r.confidence == 1.0
    assert any("Rust" in s.summary for s in r.signals)
    assert all(a == "Bearer bearer-xxx" for a in seen_auth if a)


@pytest.mark.asyncio
async def test_enrich_handles_x_dot_com_url_form() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/users/by/username/" in req.url.path:
            return httpx.Response(200, json=_user())
        return httpx.Response(200, json=_tweets())
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://x.com/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_user_not_found() -> None:
    handler = lambda req: httpx.Response(404, json={"errors": [{"detail": "Not Found"}]})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://twitter.com/ghost", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_401() -> None:
    handler = lambda req: httpx.Response(401, json={"title": "Unauthorized"})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://twitter.com/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_429_quota() -> None:
    handler = lambda req: httpx.Response(429, json={"title": "Too Many Requests"})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://twitter.com/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_5xx() -> None:
    handler = lambda req: httpx.Response(503)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://twitter.com/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_network_failure() -> None:
    def handler(req): raise httpx.ConnectError("refused", request=req)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://twitter.com/alice", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_caps_signals_at_5() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/users/by/username/" in req.url.path:
            return httpx.Response(200, json=_user())
        return httpx.Response(200, json={
            "data": [
                {"id": f"t{i}", "text": f"tweet {i}",
                 "created_at": "2025-01-01T00:00:00.000Z",
                 "public_metrics": {"like_count": 1, "retweet_count": 0, "reply_count": 0, "quote_count": 0}}
                for i in range(20)
            ]
        })
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://twitter.com/alice", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None and len(r.signals) <= 5


@pytest.mark.asyncio
async def test_enrich_propagates_low_confidence() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/users/by/username/" in req.url.path:
            return httpx.Response(200, json=_user())
        return httpx.Response(200, json=_tweets())
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://x.com/alice", confidence=0.5)
    r = await p.enrich(hint)
    assert r is not None and r.confidence == 0.5 and r.discovered


@pytest.mark.asyncio
async def test_enrich_with_name_only_hint_returns_none() -> None:
    handler = lambda req: httpx.Response(200, json={})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(name="Alice Doe", confidence=0.5)
    assert await p.enrich(hint) is None
```

---

### Task 21: Twitter/X — implementation

**Files:**
- Create: `src/recruiter/enrichment/twitter.py`
- Modify: `src/recruiter/enrichment/__init__.py`

```python
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import ClassVar

import httpx

from recruiter.enrichment.provider import (
    EnrichmentHint,
    EnrichmentResult,
    EnrichmentSignal,
    register,
)

logger = logging.getLogger(__name__)

TW_BASE = "https://api.twitter.com/2"


def _handle_from_url(url: str) -> str | None:
    m = re.search(r"(?:twitter\.com|x\.com)/([A-Za-z0-9_]{1,15})", url or "")
    if not m:
        return None
    handle = m.group(1)
    if handle in {"i", "search", "home", "explore", "notifications"}:
        return None
    return handle


@register("twitter")
class TwitterProvider:
    name: ClassVar[str] = "twitter"
    domains: ClassVar[list[str]] = ["twitter.com", "x.com"]

    def __init__(
        self,
        *,
        bearer_token: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._bearer = bearer_token
        self._client = httpx.AsyncClient(transport=transport, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._bearer}"}

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        handle = _handle_from_url(hint.url) if hint.url else None
        if not handle:
            return None

        try:
            user_r = await self._client.get(
                f"{TW_BASE}/users/by/username/{handle}",
                headers=self._headers(),
                params={"user.fields": "description,public_metrics,url"},
            )
        except httpx.HTTPError as exc:
            logger.info("twitter user fetch failed for %s: %s", handle, exc)
            return None
        if user_r.status_code != 200:
            logger.info("twitter user fetch %s for %s", user_r.status_code, handle)
            return None
        try:
            user_data = user_r.json().get("data") or {}
        except ValueError:
            return None
        if not user_data.get("id"):
            return None
        uid = user_data["id"]

        try:
            tw_r = await self._client.get(
                f"{TW_BASE}/users/{uid}/tweets",
                headers=self._headers(),
                params={
                    "max_results": 5,
                    "tweet.fields": "created_at,public_metrics",
                },
            )
        except httpx.HTTPError as exc:
            logger.info("twitter tweets fetch failed for %s: %s", uid, exc)
            return None
        if tw_r.status_code != 200:
            return None
        try:
            tweets = tw_r.json().get("data") or []
        except ValueError:
            return None

        signals: list[EnrichmentSignal] = []
        desc = user_data.get("description") or ""
        site = user_data.get("url") or ""
        metrics = user_data.get("public_metrics") or {}
        signals.append(EnrichmentSignal(
            type="profile",
            summary=f"X/Twitter @{handle}: {metrics.get('followers_count',0)} followers, "
                    f"{metrics.get('tweet_count',0)} posts."
                    + (f" Bio: {desc[:200]}" if desc else "")
                    + (f" {site}" if site else ""),
            url=f"https://x.com/{handle}",
        ))
        for t in tweets[:4]:
            ts = t.get("created_at")
            try:
                ts_parsed = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
            except (ValueError, AttributeError):
                ts_parsed = None
            m = t.get("public_metrics") or {}
            signals.append(EnrichmentSignal(
                type="post",
                summary=f"@{handle}: {(t.get('text') or '')[:160]} "
                        f"({m.get('like_count',0)} likes, {m.get('retweet_count',0)} RTs)",
                url=f"https://x.com/{handle}/status/{t.get('id')}" if t.get("id") else None,
                timestamp=ts_parsed,
            ))

        summary = f"X/Twitter @{handle}: {metrics.get('followers_count',0)} followers."
        return EnrichmentResult(
            source="twitter",
            profile_url=f"https://x.com/{handle}",
            confidence=hint.confidence,
            discovered=hint.confidence < 1.0,
            signals=signals[:5],
            summary=summary,
        )
```

- [ ] **Step 2: Wire registration + tests + commit**

Append to `__init__.py`: `from recruiter.enrichment import twitter as _twitter  # noqa: F401`.

```bash
uv run pytest tests/unit/test_enrichment_twitter.py -v
```
Expected: all 10 PASS. Commit: `feat(enrichment): add Twitter/X provider`.

---

### Task 22: Blog/website — failing tests

**Files:**
- Create: `tests/unit/test_enrichment_blog.py`

This provider is the catch-all. Given a candidate-listed URL with no matching domain in the other providers, fetch the page, strip HTML, summarize via the existing `LLMClient`. Only used for explicit-link hints (confidence 1.0); discovery doesn't route to it.

- [ ] **Step 1: Write the test file**

```python
import httpx
import pytest

from recruiter.enrichment.blog import BlogProvider
from recruiter.enrichment.provider import EnrichmentHint


class FakeLLM:
    """Minimal stand-in for LLMClient.chat — returns a canned summary."""
    def __init__(self, output: str = "A blog about Rust async patterns.") -> None:
        self._output = output
        self.calls: list[list] = []

    async def chat(self, messages, *, system=None, max_tokens=2048, temperature=0.0):
        self.calls.append(messages)
        return self._output


def _make_provider(transport: httpx.MockTransport, llm=None) -> BlogProvider:
    return BlogProvider(llm=llm or FakeLLM(), transport=transport)


@pytest.mark.asyncio
async def test_enrich_html_page_returns_signal_with_summary() -> None:
    html = """
    <html><head><title>Alice's blog</title></head>
    <body>
      <h1>Async Rust patterns</h1>
      <p>Tokio gives you a runtime. lifetimes are the hard part.</p>
    </body></html>
    """
    handler = lambda req: httpx.Response(200, text=html, headers={"content-type": "text/html"})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://alice.dev/posts/rust", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert r.source == "blog"
    assert r.profile_url == "https://alice.dev/posts/rust"
    assert len(r.signals) == 1
    assert r.signals[0].type == "writing"
    assert "Rust" in r.signals[0].summary or "blog" in r.signals[0].summary


@pytest.mark.asyncio
async def test_enrich_strips_html_tags_before_passing_to_llm() -> None:
    html = "<html><body><p>Hello <strong>world</strong></p><script>bad();</script></body></html>"
    handler = lambda req: httpx.Response(200, text=html, headers={"content-type": "text/html"})
    fake = FakeLLM()
    p = _make_provider(httpx.MockTransport(handler), llm=fake)
    hint = EnrichmentHint(url="https://alice.dev/", confidence=1.0)
    await p.enrich(hint)
    # The LLM input must not contain raw HTML or <script> contents.
    assert fake.calls
    sent = " ".join(m.content for m in fake.calls[-1])
    assert "<p>" not in sent
    assert "<script>" not in sent
    assert "bad();" not in sent


@pytest.mark.asyncio
async def test_enrich_returns_none_on_404() -> None:
    handler = lambda req: httpx.Response(404)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://alice.dev/missing", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_5xx() -> None:
    handler = lambda req: httpx.Response(503)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://alice.dev/", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_network_failure() -> None:
    def handler(req): raise httpx.ConnectError("refused", request=req)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://alice.dev/", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_non_html_content_type() -> None:
    """A PDF / image / binary URL is not summarizable; skip rather than crash."""
    handler = lambda req: httpx.Response(
        200, content=b"%PDF-1.4...", headers={"content-type": "application/pdf"}
    )
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://alice.dev/cv.pdf", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_truncates_very_long_pages_before_llm() -> None:
    long_text = "<p>" + ("Rust async! " * 50000) + "</p>"
    handler = lambda req: httpx.Response(200, text=long_text, headers={"content-type": "text/html"})
    fake = FakeLLM()
    p = _make_provider(httpx.MockTransport(handler), llm=fake)
    hint = EnrichmentHint(url="https://alice.dev/", confidence=1.0)
    await p.enrich(hint)
    # The provider must cap the LLM input (the spec doesn't pin the
    # number, but it must be finite — pick 8000 chars).
    sent = " ".join(m.content for m in fake.calls[-1])
    assert len(sent) <= 12000   # 8000 content + headroom for the prompt template


@pytest.mark.asyncio
async def test_enrich_with_name_only_hint_returns_none() -> None:
    handler = lambda req: httpx.Response(200, text="x")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(name="Alice Doe", confidence=0.5)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_when_llm_summary_is_empty() -> None:
    """Empty LLM response → can't surface a useful signal → None."""
    html = "<html><body><p>Hi</p></body></html>"
    handler = lambda req: httpx.Response(200, text=html, headers={"content-type": "text/html"})
    fake = FakeLLM(output="   ")
    p = _make_provider(httpx.MockTransport(handler), llm=fake)
    hint = EnrichmentHint(url="https://alice.dev/", confidence=1.0)
    assert await p.enrich(hint) is None
```

---

### Task 23: Blog/website — implementation

**Files:**
- Create: `src/recruiter/enrichment/blog.py`
- Modify: `src/recruiter/enrichment/__init__.py`

```python
from __future__ import annotations

import logging
import re
from typing import Any, ClassVar

import httpx

from recruiter.enrichment.provider import (
    EnrichmentHint,
    EnrichmentResult,
    EnrichmentSignal,
    register,
)

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)
_MAX_BODY_CHARS = 8000

SYSTEM_PROMPT = (
    "You are summarizing a candidate's personal blog or website page for a "
    "recruiter. Reply with one or two sentences in plain English. Mention "
    "the topic and what the page reveals about the author's technical interests. "
    "Do not invent facts."
)


def _strip(html: str) -> str:
    s = _SCRIPT_RE.sub(" ", html)
    s = _STYLE_RE.sub(" ", s)
    s = _HTML_TAG_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


@register("blog")
class BlogProvider:
    name: ClassVar[str] = "blog"
    # Empty domains list — discovery never routes to this provider; it
    # only handles explicit candidate.links URLs that didn't match anyone.
    domains: ClassVar[list[str]] = []

    def __init__(
        self,
        *,
        llm: Any = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # llm is the existing LLMClient Protocol. Lazy import to avoid
        # circulars during test collection.
        if llm is None:
            from recruiter.llm.client import LLMClient  # noqa: F401
            raise ValueError("BlogProvider requires an LLMClient instance")
        self._llm = llm
        self._client = httpx.AsyncClient(
            transport=transport, timeout=10.0, follow_redirects=True
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None:
        if not hint.url:
            return None

        try:
            r = await self._client.get(hint.url)
        except httpx.HTTPError as exc:
            logger.info("blog fetch failed for %s: %s", hint.url, exc)
            return None
        if r.status_code != 200:
            return None
        ctype = (r.headers.get("content-type") or "").lower()
        if "text/html" not in ctype and "application/xhtml" not in ctype:
            return None

        text = _strip(r.text)
        if not text:
            return None
        text = text[:_MAX_BODY_CHARS]

        from recruiter.llm.client import LLMMessage
        try:
            summary = await self._llm.chat(
                [LLMMessage(role="user", content=f"URL: {hint.url}\n\nPage content:\n{text}")],
                system=SYSTEM_PROMPT,
                max_tokens=300,
                temperature=0.0,
            )
        except Exception as exc:
            logger.info("blog LLM summary failed for %s: %s", hint.url, exc)
            return None

        summary = (summary or "").strip()
        if not summary:
            return None

        signal = EnrichmentSignal(
            type="writing",
            summary=summary[:300],
            url=hint.url,
        )
        return EnrichmentResult(
            source="blog",
            profile_url=hint.url,
            confidence=hint.confidence,
            discovered=hint.confidence < 1.0,
            signals=[signal],
            summary=summary[:500],
        )
```

> **Decision (in-plan):** the `BlogProvider` factory in `provider.py::_instantiate` returns `None` because it can't be built without an `LLMClient`. The pipeline (T25) wires the LLM in at orchestration time by calling `BlogProvider(llm=...)` directly, bypassing the registry for this one provider. The `@register("blog")` decoration is still useful for `resolve_for_domain` (used by the URL router); the pipeline just instantiates it explicitly.

- [ ] **Step 2: Wire registration**

Append to `src/recruiter/enrichment/__init__.py`:

```python
from recruiter.enrichment import blog as _blog  # noqa: F401
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/unit/test_enrichment_blog.py -v
```
Expected: all 9 PASS.

- [ ] **Step 4: Commit**

```bash
git add src/recruiter/enrichment/blog.py \
        src/recruiter/enrichment/__init__.py \
        tests/unit/test_enrichment_blog.py
git commit -m "feat(enrichment): add blog/website generic provider"
```

---

### Task 24: Discovery layer

**Files:**
- Create: `src/recruiter/enrichment/discovery.py`
- Create: `tests/unit/test_enrichment_discovery.py`

The discovery layer issues `"<name>" "<employer>" site:<domain>` searches via the active sourcing provider, then turns each top result into a low-confidence (`0.5`) `EnrichmentHint`.

- [ ] **Step 1: Failing tests**

```python
import httpx
import pytest

from recruiter.enrichment.discovery import discover
from recruiter.enrichment.provider import EnrichmentHint
from recruiter.sourcing.provider import SearchError, SearchResult


class FakeSourcing:
    """Stand-in for a SourcingProvider. Records every query."""
    def __init__(self, results_by_query: dict[str, list[SearchResult]] | None = None,
                 raise_for: dict[str, Exception] | None = None) -> None:
        self.queries: list[tuple[str, int]] = []
        self._results = results_by_query or {}
        self._raise = raise_for or {}

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        self.queries.append((query, limit))
        if query in self._raise:
            raise self._raise[query]
        return self._results.get(query, [])


def _registry_with(*provider_classes):
    """Helper: replaces the enrichment registry for one test."""
    from recruiter.enrichment.provider import _REGISTRY
    saved = dict(_REGISTRY)
    _REGISTRY.clear()
    for cls in provider_classes:
        _REGISTRY[cls.name] = cls
    return saved


def _restore(saved):
    from recruiter.enrichment.provider import _REGISTRY
    _REGISTRY.clear()
    _REGISTRY.update(saved)


class _MastoProvider:
    name = "mastodon"
    domains = ["mastodon.social", "fosstodon.org"]
    def __init__(self, *_, **__): pass
    async def enrich(self, hint): return None
    async def aclose(self): pass


class _GitHubProvider:
    name = "github"
    domains = ["github.com"]
    def __init__(self, *_, **__): pass
    async def enrich(self, hint): return None
    async def aclose(self): pass


@pytest.mark.asyncio
async def test_discover_issues_one_query_per_provider_domain_pair() -> None:
    saved = _registry_with(_MastoProvider, _GitHubProvider)
    try:
        sourcing = FakeSourcing()
        fake_settings = type("S", (), {
            "enrichment_sources": {},
            "github_token_enc": None,
            "enrichment_twitter_api_key_enc": None,
            "enrichment_youtube_api_key_enc": None,
            "enrichment_stackexchange_key_enc": None,
        })()
        await discover(
            name="Alice Doe",
            employer="Acme",
            sourcing=sourcing,
            settings=fake_settings,
        )
        # 2 mastodon domains + 1 github domain = 3 queries.
        assert len(sourcing.queries) == 3
        for q, _ in sourcing.queries:
            assert '"Alice Doe"' in q
            assert '"Acme"' in q
            assert "site:" in q
    finally:
        _restore(saved)


@pytest.mark.asyncio
async def test_discover_returns_hints_at_confidence_0_5() -> None:
    saved = _registry_with(_GitHubProvider)
    try:
        sourcing = FakeSourcing(results_by_query={
            '"Alice" "Acme" site:github.com': [
                SearchResult(name="Alice", url="https://github.com/alice",
                             snippet="rust dev", source="web"),
            ]
        })
        fake_settings = type("S", (), {"enrichment_sources": {}, "github_token_enc": None})()
        hints = await discover("Alice", "Acme", sourcing=sourcing, settings=fake_settings)
        assert len(hints) == 1
        assert hints[0].confidence == 0.5
        assert hints[0].url == "https://github.com/alice"
        assert hints[0].source == "github"
    finally:
        _restore(saved)


@pytest.mark.asyncio
async def test_discover_skips_disabled_sources() -> None:
    saved = _registry_with(_MastoProvider, _GitHubProvider)
    try:
        sourcing = FakeSourcing()
        fake_settings = type("S", (), {
            "enrichment_sources": {"mastodon": False},
            "github_token_enc": None,
        })()
        await discover("Alice", "Acme", sourcing=sourcing, settings=fake_settings)
        # Only github queries should fire.
        assert all("github.com" in q for q, _ in sourcing.queries)
    finally:
        _restore(saved)


@pytest.mark.asyncio
async def test_discover_returns_empty_when_sourcing_none() -> None:
    """No active sourcing provider → no discovery (no errors raised)."""
    hints = await discover("Alice", "Acme", sourcing=None, settings=type("S", (), {})())
    assert hints == []


@pytest.mark.asyncio
async def test_discover_skips_query_when_sourcing_raises() -> None:
    saved = _registry_with(_GitHubProvider)
    try:
        sourcing = FakeSourcing(raise_for={
            '"Alice" "Acme" site:github.com': SearchError("rate limit", transient=True)
        })
        fake_settings = type("S", (), {"enrichment_sources": {}, "github_token_enc": None})()
        hints = await discover("Alice", "Acme", sourcing=sourcing, settings=fake_settings)
        # Failure is non-fatal: just no hint for that domain.
        assert hints == []
    finally:
        _restore(saved)


@pytest.mark.asyncio
async def test_discover_takes_only_top_result_per_domain() -> None:
    saved = _registry_with(_GitHubProvider)
    try:
        sourcing = FakeSourcing(results_by_query={
            '"Alice" "Acme" site:github.com': [
                SearchResult(name="Alice", url="https://github.com/alice", snippet="", source="web"),
                SearchResult(name="Other Alice", url="https://github.com/other", snippet="", source="web"),
            ]
        })
        fake_settings = type("S", (), {"enrichment_sources": {}, "github_token_enc": None})()
        hints = await discover("Alice", "Acme", sourcing=sourcing, settings=fake_settings)
        assert len(hints) == 1
        assert hints[0].url == "https://github.com/alice"
    finally:
        _restore(saved)


@pytest.mark.asyncio
async def test_discover_handles_empty_employer() -> None:
    """No employer → query is just '"<name>" site:<domain>'."""
    saved = _registry_with(_GitHubProvider)
    try:
        sourcing = FakeSourcing()
        fake_settings = type("S", (), {"enrichment_sources": {}, "github_token_enc": None})()
        await discover("Alice", "", sourcing=sourcing, settings=fake_settings)
        for q, _ in sourcing.queries:
            assert '"Alice"' in q
            assert '"Acme"' not in q
    finally:
        _restore(saved)


@pytest.mark.asyncio
async def test_discover_skips_blog_provider_with_empty_domains() -> None:
    """BlogProvider has domains=[] — it must not cause a degenerate query."""
    class _Blog:
        name = "blog"
        domains: list[str] = []
        def __init__(self, *_, **__): pass
        async def enrich(self, hint): return None
        async def aclose(self): pass

    saved = _registry_with(_Blog, _GitHubProvider)
    try:
        sourcing = FakeSourcing()
        fake_settings = type("S", (), {"enrichment_sources": {}, "github_token_enc": None})()
        await discover("Alice", "Acme", sourcing=sourcing, settings=fake_settings)
        for q, _ in sourcing.queries:
            assert "site:" in q  # never a degenerate site:<empty>
    finally:
        _restore(saved)
```

- [ ] **Step 2: Implementation**

```python
from __future__ import annotations

import logging
from typing import Any

from recruiter.enrichment.provider import EnrichmentHint, _REGISTRY
from recruiter.sourcing.provider import SearchError, SearchProvider

logger = logging.getLogger(__name__)


async def discover(
    name: str,
    employer: str,
    *,
    sourcing: SearchProvider | None,
    settings: Any,
) -> list[EnrichmentHint]:
    """Issue per-(provider, domain) `"<name>" "<employer>" site:<domain>`
    queries via the active sourcing provider. Top result per query becomes
    an EnrichmentHint at confidence 0.5.

    Failures (no sourcing configured, per-query SearchError) are
    non-fatal: the function simply returns whatever it managed to collect.
    """
    if sourcing is None:
        return []

    toggles: dict[str, bool] = getattr(settings, "enrichment_sources", None) or {}

    hints: list[EnrichmentHint] = []
    for source_name, cls in _REGISTRY.items():
        if toggles.get(source_name, True) is False:
            continue
        domains = getattr(cls, "domains", None) or []
        for domain in domains:
            quoted_name = f'"{name}"' if name else ""
            quoted_emp = f' "{employer}"' if employer else ""
            query = f'{quoted_name}{quoted_emp} site:{domain}'.strip()
            try:
                results = await sourcing.search(query, limit=3)
            except SearchError as exc:
                logger.info("discovery query failed for %s: %s", domain, exc)
                continue
            except Exception as exc:  # pragma: no cover - defensive
                logger.info("discovery query crashed for %s: %s", domain, exc)
                continue
            if not results:
                continue
            top = results[0]
            hints.append(EnrichmentHint(
                url=top.url,
                confidence=0.5,
                source=source_name,
                name=name,
                employer=employer or None,
            ))
    return hints
```

- [ ] **Step 3: Run tests + commit**

```bash
uv run pytest tests/unit/test_enrichment_discovery.py -v
```
Expected: all 8 PASS.

```bash
git add src/recruiter/enrichment/discovery.py tests/unit/test_enrichment_discovery.py
git commit -m "feat(enrichment): add discovery layer using active sourcing provider"
```

---

### Task 25: Pipeline (top-level enrich orchestrator)

**Files:**
- Create: `src/recruiter/enrichment/pipeline.py`
- Create: `tests/unit/test_enrichment_pipeline.py`

`enrich(candidate, job, settings, llm) -> EnrichmentBundle`. Steps:

1. Collect explicit hints from `candidate.links` at confidence 1.0, routed by domain.
2. If `job.enrichment_consent`: run discovery to get 0.5 hints (deduped against explicit hints).
3. For each hint, instantiate the matching provider; for keyless ones, no settings dependency.
4. Run providers in parallel via `asyncio.gather(..., return_exceptions=True)`.
5. Pass the union of results into `identity.consolidate(...)` with anchor URLs/emails from `candidate.links`/`candidate.email`.
6. Build the `EnrichmentBundle` with `fetched_at = now`, `expires_at = now + 30d`.

- [ ] **Step 1: Failing tests**

```python
from datetime import datetime, timedelta, timezone

import pytest

from recruiter.enrichment.pipeline import enrich, BUNDLE_TTL
from recruiter.enrichment.provider import (
    EnrichmentBundle,
    EnrichmentHint,
    EnrichmentResult,
    EnrichmentSignal,
    _REGISTRY,
)


class _FakeProvider:
    """Returns a canned EnrichmentResult for any hint matching its domain."""
    name = "fake"
    domains = ["fake.example"]

    def __init__(self, *_, output: EnrichmentResult | None = None, **__):
        self._output = output
        self.calls: list[EnrichmentHint] = []

    async def enrich(self, hint):
        self.calls.append(hint)
        return self._output

    async def aclose(self):
        pass


def _result(source: str = "fake") -> EnrichmentResult:
    return EnrichmentResult(
        source=source,
        profile_url="https://fake.example/u/alice",
        confidence=1.0,
        discovered=False,
        signals=[EnrichmentSignal(type="profile", summary="Alice on fake.example")],
        summary="Alice's fake.example profile.",
    )


class _Candidate:
    def __init__(self, links=None, email=None, full_name="Alice Doe"):
        self.full_name = full_name
        self.email = email
        self.links = links or []


class _Job:
    def __init__(self, enrichment_consent=False):
        self.enrichment_consent = enrichment_consent
        self.title = "Senior Rust"
        self.description = "..."


def _settings(toggles=None):
    return type("S", (), {
        "enrichment_enabled": True,
        "enrichment_sources": toggles or {},
        "github_token_enc": None,
        "enrichment_twitter_api_key_enc": None,
        "enrichment_youtube_api_key_enc": None,
        "enrichment_stackexchange_key_enc": None,
        "search_provider": None,
        "search_api_key_enc": None,
        "search_engine_id": None,
    })()


@pytest.fixture
def _replace_registry(monkeypatch):
    saved = dict(_REGISTRY)
    _REGISTRY.clear()
    yield _REGISTRY
    _REGISTRY.clear()
    _REGISTRY.update(saved)


@pytest.mark.asyncio
async def test_enrich_routes_explicit_link_to_matching_provider(_replace_registry, monkeypatch):
    fake = _FakeProvider(output=_result())
    _replace_registry["fake"] = lambda *a, **k: fake
    # Bypass the registry's default _instantiate; we inject the instance directly.
    from recruiter.enrichment import pipeline as pipe_mod
    monkeypatch.setattr(pipe_mod, "_resolve_providers",
                        lambda settings, llm: [fake])

    cand = _Candidate(links=[{"url": "https://fake.example/u/alice", "kind": "profile"}])
    job = _Job(enrichment_consent=False)
    bundle = await enrich(candidate=cand, job=job, settings=_settings(), llm=None)
    assert isinstance(bundle, EnrichmentBundle)
    assert len(bundle.results) == 1
    assert bundle.results[0].source == "fake"
    assert any(h.confidence == 1.0 for h in fake.calls)


@pytest.mark.asyncio
async def test_enrich_skips_discovery_when_consent_false(monkeypatch):
    """consent=False → no discovery query, only candidate.links are used."""
    from recruiter.enrichment import pipeline as pipe_mod
    discovery_called = False

    async def fake_discover(*a, **kw):
        nonlocal discovery_called
        discovery_called = True
        return []

    monkeypatch.setattr(pipe_mod, "discover", fake_discover)
    monkeypatch.setattr(pipe_mod, "_resolve_providers", lambda *a, **k: [])

    cand = _Candidate(links=[])
    job = _Job(enrichment_consent=False)
    await enrich(candidate=cand, job=job, settings=_settings(), llm=None)
    assert discovery_called is False


@pytest.mark.asyncio
async def test_enrich_runs_discovery_when_consent_true(monkeypatch):
    from recruiter.enrichment import pipeline as pipe_mod
    discovery_called = False

    async def fake_discover(name, employer, *, sourcing, settings):
        nonlocal discovery_called
        discovery_called = True
        return []

    monkeypatch.setattr(pipe_mod, "discover", fake_discover)
    monkeypatch.setattr(pipe_mod, "_resolve_providers", lambda *a, **k: [])

    cand = _Candidate(links=[])
    job = _Job(enrichment_consent=True)
    await enrich(candidate=cand, job=job, settings=_settings(), llm=None)
    assert discovery_called is True


@pytest.mark.asyncio
async def test_enrich_runs_providers_in_parallel(monkeypatch):
    """Three slow providers should not run sequentially. Use a counter to
    confirm overlap."""
    import asyncio
    from recruiter.enrichment import pipeline as pipe_mod

    in_flight = 0
    max_in_flight = 0

    class Slow:
        name = "slow"
        domains = ["slow.example"]
        def __init__(self, *_, **__): ...
        async def enrich(self, hint):
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.05)
            in_flight -= 1
            return _result(source=hint.source or "slow")
        async def aclose(self): ...

    slows = [Slow() for _ in range(3)]
    monkeypatch.setattr(pipe_mod, "_resolve_providers", lambda *a, **k: slows)

    cand = _Candidate(links=[
        {"url": "https://slow.example/u/a"},
        {"url": "https://slow.example/u/b"},
        {"url": "https://slow.example/u/c"},
    ])
    job = _Job(enrichment_consent=False)
    await enrich(candidate=cand, job=job, settings=_settings(), llm=None)
    assert max_in_flight >= 2  # actually parallel


@pytest.mark.asyncio
async def test_enrich_drops_results_below_0_5(monkeypatch):
    from recruiter.enrichment import pipeline as pipe_mod

    class WeakProvider:
        name = "weak"
        domains = ["weak.example"]
        def __init__(self, *_, **__): ...
        async def enrich(self, hint):
            return EnrichmentResult(
                source="weak",
                profile_url="https://weak.example/u",
                confidence=0.3,
                discovered=True,
                signals=[],
                summary="weak",
            )
        async def aclose(self): ...

    monkeypatch.setattr(pipe_mod, "_resolve_providers", lambda *a, **k: [WeakProvider()])

    cand = _Candidate(links=[{"url": "https://weak.example/u"}])
    job = _Job(enrichment_consent=False)
    bundle = await enrich(candidate=cand, job=job, settings=_settings(), llm=None)
    assert bundle.results == []


@pytest.mark.asyncio
async def test_enrich_records_provider_errors(monkeypatch):
    from recruiter.enrichment import pipeline as pipe_mod

    class CrashProvider:
        name = "crash"
        domains = ["crash.example"]
        def __init__(self, *_, **__): ...
        async def enrich(self, hint):
            raise RuntimeError("boom")
        async def aclose(self): ...

    monkeypatch.setattr(pipe_mod, "_resolve_providers", lambda *a, **k: [CrashProvider()])

    cand = _Candidate(links=[{"url": "https://crash.example/u"}])
    job = _Job(enrichment_consent=False)
    bundle = await enrich(candidate=cand, job=job, settings=_settings(), llm=None)
    assert any(e.get("source") == "crash" for e in bundle.errors)
    # Other results still come through (none here, but no crash either).
    assert bundle.results == []


@pytest.mark.asyncio
async def test_enrich_sets_ttl_correctly(monkeypatch):
    from recruiter.enrichment import pipeline as pipe_mod
    monkeypatch.setattr(pipe_mod, "_resolve_providers", lambda *a, **k: [])
    cand = _Candidate()
    job = _Job(enrichment_consent=False)
    bundle = await enrich(candidate=cand, job=job, settings=_settings(), llm=None)
    delta = bundle.expires_at - bundle.fetched_at
    assert abs(delta - BUNDLE_TTL) < timedelta(seconds=1)


@pytest.mark.asyncio
async def test_enrich_records_discovery_consent_in_bundle(monkeypatch):
    from recruiter.enrichment import pipeline as pipe_mod

    async def fake_discover(*a, **kw): return []
    monkeypatch.setattr(pipe_mod, "discover", fake_discover)
    monkeypatch.setattr(pipe_mod, "_resolve_providers", lambda *a, **k: [])

    cand = _Candidate()
    job_consent_off = _Job(enrichment_consent=False)
    job_consent_on = _Job(enrichment_consent=True)

    b1 = await enrich(candidate=cand, job=job_consent_off, settings=_settings(), llm=None)
    b2 = await enrich(candidate=cand, job=job_consent_on, settings=_settings(), llm=None)
    assert b1.discovery_consent is False
    assert b2.discovery_consent is True


@pytest.mark.asyncio
async def test_enrich_uses_anchor_urls_from_candidate_links(monkeypatch):
    """When candidate.links contains a github.com URL, the identity engine
    should treat that as a 1.0 anchor — not require corroboration."""
    from recruiter.enrichment import pipeline as pipe_mod

    class GH:
        name = "github"
        domains = ["github.com"]
        def __init__(self, *_, **__): ...
        async def enrich(self, hint):
            return EnrichmentResult(
                source="github",
                profile_url="https://github.com/alice",
                confidence=hint.confidence,
                discovered=hint.confidence < 1.0,
                signals=[EnrichmentSignal(type="profile", summary="GH profile")],
                summary="GH",
            )
        async def aclose(self): ...

    monkeypatch.setattr(pipe_mod, "_resolve_providers", lambda *a, **k: [GH()])

    cand = _Candidate(links=[{"url": "https://github.com/alice"}], email="alice@acme.com")
    job = _Job(enrichment_consent=False)
    bundle = await enrich(candidate=cand, job=job, settings=_settings(), llm=None)
    gh_result = next(r for r in bundle.results if r.source == "github")
    assert gh_result.confidence == 1.0
```

- [ ] **Step 2: Implementation**

```python
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from recruiter.enrichment.discovery import discover
from recruiter.enrichment.identity import consolidate
from recruiter.enrichment.provider import (
    EnrichmentBundle,
    EnrichmentHint,
    EnrichmentResult,
    _REGISTRY,
)
from recruiter.sourcing.provider import resolve as resolve_sourcing

logger = logging.getLogger(__name__)

BUNDLE_TTL = timedelta(days=30)


def _resolve_providers(settings: Any, llm: Any) -> list:
    """Build provider instances from the registry. The blog provider needs
    the LLM injected; everything else uses the registry's _instantiate."""
    from recruiter.enrichment.provider import _instantiate

    out = []
    toggles: dict[str, bool] = getattr(settings, "enrichment_sources", None) or {}
    for name, cls in _REGISTRY.items():
        if toggles.get(name, True) is False:
            continue
        if name == "blog":
            if llm is None:
                continue
            try:
                out.append(cls(llm=llm))
            except Exception:
                continue
            continue
        inst = _instantiate(cls, settings)
        if inst is not None:
            out.append(inst)
    return out


def _provider_for_url(url: str, providers: list) -> Any | None:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return None
    # Strict-then-lenient: exact match wins, then suffix match.
    for p in providers:
        if host in (d.lower() for d in (p.domains or [])):
            return p
    for p in providers:
        for d in p.domains or []:
            if host.endswith("." + d.lower()):
                return p
    return None


def _route_blog_fallback(url: str, providers: list) -> Any | None:
    for p in providers:
        if p.name == "blog":
            return p
    return None


async def enrich(
    *,
    candidate: Any,
    job: Any,
    settings: Any,
    llm: Any,
) -> EnrichmentBundle:
    """Top-level enrichment orchestrator. Returns a bundle that can be
    serialised straight onto Application.enrichment."""
    fetched = datetime.now(timezone.utc)

    providers = _resolve_providers(settings, llm)

    # Phase 1: explicit-link hints (confidence 1.0).
    hints: list[EnrichmentHint] = []
    explicit_urls: list[str] = []
    for link in (candidate.links or []):
        url = (link.get("url") if isinstance(link, dict) else getattr(link, "url", None)) or ""
        if not url:
            continue
        explicit_urls.append(url)
        hints.append(EnrichmentHint(url=url, confidence=1.0))

    # Phase 2: discovery (consent-gated).
    if getattr(job, "enrichment_consent", False):
        sourcing = resolve_sourcing(settings)
        employer = ""
        # Best-effort: pull employer from the first experience entry.
        exp = getattr(candidate, "experience", None) or []
        if exp:
            first = exp[0]
            employer = (first.get("company") if isinstance(first, dict) else getattr(first, "company", "")) or ""
        try:
            disc_hints = await discover(
                getattr(candidate, "full_name", "") or "",
                employer,
                sourcing=sourcing,
                settings=settings,
            )
        except Exception as exc:
            logger.info("discovery layer failed: %s", exc)
            disc_hints = []
        # Don't double-enrich URLs we already have explicitly.
        existing = {u.lower() for u in explicit_urls}
        for h in disc_hints:
            if h.url and h.url.lower() not in existing:
                hints.append(h)

    # Phase 3: route + fan-out.
    async def _run_one(hint: EnrichmentHint) -> tuple[str, EnrichmentResult | Exception | None]:
        provider = None
        if hint.url:
            provider = _provider_for_url(hint.url, providers)
            if provider is None and hint.confidence >= 1.0:
                provider = _route_blog_fallback(hint.url, providers)
        if provider is None:
            return ("(unrouted)", None)
        try:
            r = await provider.enrich(hint)
            return (provider.name, r)
        except Exception as exc:
            return (provider.name, exc)

    raw = await asyncio.gather(*[_run_one(h) for h in hints], return_exceptions=False)

    # Close async clients.
    for p in providers:
        try:
            await p.aclose()
        except Exception:
            pass

    results: list[EnrichmentResult] = []
    errors: list[dict] = []
    for source, val in raw:
        if isinstance(val, Exception):
            errors.append({"source": source, "error": str(val), "transient": False})
        elif val is not None:
            results.append(val)

    # Phase 4: identity consolidation.
    anchor_urls = list(explicit_urls)
    anchor_emails = []
    if getattr(candidate, "email", None):
        anchor_emails.append(candidate.email)

    consolidated = consolidate(results, anchor_urls=anchor_urls, anchor_emails=anchor_emails)

    return EnrichmentBundle(
        fetched_at=fetched,
        expires_at=fetched + BUNDLE_TTL,
        discovery_consent=bool(getattr(job, "enrichment_consent", False)),
        results=consolidated,
        errors=errors,
    )
```

- [ ] **Step 3: Run tests + commit**

```bash
uv run pytest tests/unit/test_enrichment_pipeline.py -v
```
Expected: all 9 PASS.

```bash
git add src/recruiter/enrichment/pipeline.py tests/unit/test_enrichment_pipeline.py
git commit -m "feat(enrichment): add top-level enrich orchestrator"
```

---

### Task 26: Orchestrator integration + score-isolation invariant

**Files:**
- Modify: `src/recruiter/pipeline/orchestrator.py`
- Create: `tests/unit/test_orchestrator_enrichment.py`

Insert `Stage.ENRICHING` between `EXTRACTING` and `SCORED`. Crucially, `score_candidate` must be invoked with the **same arguments** whether enrichment ran or not.

- [ ] **Step 1: Modify `process_application`**

In `src/recruiter/pipeline/orchestrator.py`, after the `_apply_extracted` call and before the `score_candidate` call, insert:

```python
        # ----- enrichment stage (additive; score is unchanged) -----
        bundle = None
        settings_row = await session.get(SettingsRow, 1)
        if (
            settings_row is not None
            and settings_row.enrichment_enabled
            and not _has_fresh_bundle(app)
        ):
            await bus.publish({"type": "stage", "application_id": app.id, "stage": Stage.ENRICHING.value})
            app.stage = Stage.ENRICHING
            await session.commit()
            try:
                bundle = await enrich(
                    candidate=candidate, job=job, settings=settings_row, llm=llm
                )
                app.enrichment = bundle.model_dump(mode="json")
                session.add(EventLog(
                    application_id=app.id,
                    event_type="application.enriched",
                    payload={
                        "results": len(bundle.results),
                        "errors": len(bundle.errors),
                    },
                ))
                await session.commit()
            except Exception as exc:
                session.add(EventLog(
                    application_id=app.id,
                    event_type="enrichment.failed",
                    payload={"error": str(exc)},
                ))
                await session.commit()
                # Non-fatal: scoring proceeds.

        # ----- scoring (UNCHANGED — same arguments as before) -----
        criteria = [CriteriaItem.model_validate(c) for c in (job.criteria or [])]
        try:
            score = await score_candidate(
                job_title=job.title,
                job_description=job.description,
                criteria=criteria,
                candidate=extracted,
                llm=llm,
            )
        except Exception as exc:
            ...
```

Add the imports + helper at the top:

```python
from datetime import datetime, timedelta, timezone

from recruiter.enrichment.pipeline import enrich
from recruiter.models import SettingsRow


def _has_fresh_bundle(app) -> bool:
    """True when the persisted enrichment bundle is still within TTL."""
    if not app.enrichment:
        return False
    expires_at = app.enrichment.get("expires_at")
    if not expires_at:
        return False
    try:
        ts = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False
    return ts > datetime.now(timezone.utc)
```

- [ ] **Step 2: Score-isolation tests**

Create `tests/unit/test_orchestrator_enrichment.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch

from recruiter.events import EventBus
from recruiter.models import Application, Candidate, Job, SettingsRow, Stage
from recruiter.pipeline.orchestrator import process_application
from recruiter.pipeline.router import RoutedInput


class _FakeBus:
    def __init__(self): self.events = []
    async def publish(self, ev): self.events.append(ev)


class _FakeLLM:
    """Minimal LLM stub. Records calls so we can assert score args don't
    include enrichment data."""
    def __init__(self):
        self.score_calls = []

    async def chat(self, *a, **kw): return ""
    async def chat_structured(self, *a, **kw):
        # When called from scorer, record the messages for inspection.
        self.score_calls.append((a, kw))
        from recruiter.pipeline.scorer import ScoreResult
        return ScoreResult(score=85, breakdown=[], rationale="ok")


@pytest.mark.asyncio
async def test_score_args_identical_with_and_without_enrichment(
    session, engine, monkeypatch
):
    """Decision 1 invariant: score_candidate is invoked with the same
    arguments whether enrichment ran or not."""
    job = Job(title="Rust", description="d", criteria=[], enrichment_consent=False)
    cand = Candidate(full_name="Alice")
    session.add_all([job, cand])
    await session.flush()
    app = Application(job_id=job.id, candidate_id=cand.id, stage=Stage.EXTRACTING)
    session.add(app)
    settings_row = SettingsRow(id=1, enrichment_enabled=False)
    session.add(settings_row)
    await session.commit()

    captured: list[dict] = []

    async def spy_score(**kwargs):
        captured.append(dict(kwargs))
        from recruiter.pipeline.scorer import ScoreResult
        return ScoreResult(score=85, breakdown=[], rationale="ok")

    monkeypatch.setattr("recruiter.pipeline.orchestrator.score_candidate", spy_score)
    # Patch extractor so we don't hit the LLM.
    from recruiter.schemas.extraction import ExtractedCandidate
    async def fake_extract(*a, **kw):
        return ExtractedCandidate(full_name="Alice", skills=[], experience=[], education=[], links=[])
    monkeypatch.setattr("recruiter.pipeline.orchestrator.extract_candidate", fake_extract)

    bus = _FakeBus()
    llm = _FakeLLM()

    # Run 1: enrichment OFF
    await process_application(application_id=app.id, routed=RoutedInput(kind="paste", text="x"),
                               engine=engine, llm=llm, bus=bus)
    args_off = captured[-1]

    # Reset app stage so we can re-process.
    app.stage = Stage.EXTRACTING
    settings_row.enrichment_enabled = True
    await session.commit()

    # Run 2: enrichment ON (but no providers configured → no results)
    monkeypatch.setattr("recruiter.enrichment.pipeline._resolve_providers",
                        lambda *a, **k: [])
    await process_application(application_id=app.id, routed=RoutedInput(kind="paste", text="x"),
                               engine=engine, llm=llm, bus=bus)
    args_on = captured[-1]

    # The score args must be byte-identical between the two runs.
    assert args_off == args_on


@pytest.mark.asyncio
async def test_enrichment_failure_does_not_break_scoring(session, engine, monkeypatch):
    """If enrich() raises, the orchestrator logs and continues to score."""
    job = Job(title="t", description="d", criteria=[], enrichment_consent=True)
    cand = Candidate(full_name="Alice")
    session.add_all([job, cand])
    await session.flush()
    app = Application(job_id=job.id, candidate_id=cand.id, stage=Stage.EXTRACTING)
    session.add(app)
    session.add(SettingsRow(id=1, enrichment_enabled=True))
    await session.commit()

    from recruiter.schemas.extraction import ExtractedCandidate
    async def fake_extract(*a, **kw):
        return ExtractedCandidate(full_name="Alice", skills=[], experience=[], education=[], links=[])
    monkeypatch.setattr("recruiter.pipeline.orchestrator.extract_candidate", fake_extract)

    async def crash(**kw): raise RuntimeError("boom")
    monkeypatch.setattr("recruiter.pipeline.orchestrator.enrich", crash)

    scored = False
    async def fake_score(**kw):
        nonlocal scored
        scored = True
        from recruiter.pipeline.scorer import ScoreResult
        return ScoreResult(score=70, breakdown=[], rationale="ok")
    monkeypatch.setattr("recruiter.pipeline.orchestrator.score_candidate", fake_score)

    await process_application(application_id=app.id, routed=RoutedInput(kind="paste", text="x"),
                               engine=engine, llm=_FakeLLM(), bus=_FakeBus())
    assert scored is True


@pytest.mark.asyncio
async def test_fresh_bundle_within_ttl_is_reused(session, engine, monkeypatch):
    """If application.enrichment.expires_at is in the future, skip enrichment."""
    from datetime import datetime, timedelta, timezone
    future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()

    job = Job(title="t", description="d", criteria=[], enrichment_consent=True)
    cand = Candidate(full_name="Alice")
    session.add_all([job, cand])
    await session.flush()
    app = Application(
        job_id=job.id, candidate_id=cand.id, stage=Stage.EXTRACTING,
        enrichment={"expires_at": future, "results": [], "errors": [], "discovery_consent": True,
                    "fetched_at": datetime.now(timezone.utc).isoformat()},
    )
    session.add(app)
    session.add(SettingsRow(id=1, enrichment_enabled=True))
    await session.commit()

    from recruiter.schemas.extraction import ExtractedCandidate
    async def fake_extract(*a, **kw):
        return ExtractedCandidate(full_name="Alice", skills=[], experience=[], education=[], links=[])
    monkeypatch.setattr("recruiter.pipeline.orchestrator.extract_candidate", fake_extract)

    enrich_called = False
    async def fake_enrich(**kw):
        nonlocal enrich_called
        enrich_called = True
        from recruiter.enrichment.provider import EnrichmentBundle
        return EnrichmentBundle(
            fetched_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            discovery_consent=True, results=[], errors=[],
        )
    monkeypatch.setattr("recruiter.pipeline.orchestrator.enrich", fake_enrich)

    async def fake_score(**kw):
        from recruiter.pipeline.scorer import ScoreResult
        return ScoreResult(score=70, breakdown=[], rationale="ok")
    monkeypatch.setattr("recruiter.pipeline.orchestrator.score_candidate", fake_score)

    await process_application(application_id=app.id, routed=RoutedInput(kind="paste", text="x"),
                               engine=engine, llm=_FakeLLM(), bus=_FakeBus())
    assert enrich_called is False
```

> **Note:** the `engine` fixture is the existing async engine fixture from `tests/conftest.py`; if missing, follow the existing test patterns in `tests/unit/test_orchestrator.py` (or wherever orchestrator tests live).

- [ ] **Step 3: Run tests + commit**

```bash
uv run pytest tests/unit/test_orchestrator_enrichment.py -v
```
Expected: all 3 PASS. The first one enforces Decision 1.

```bash
git add src/recruiter/pipeline/orchestrator.py tests/unit/test_orchestrator_enrichment.py
git commit -m "feat(enrichment): integrate Stage.ENRICHING into orchestrator"
```

---

### Task 27: API — `POST /applications/{id}/re-enrich` + schema fields

**Files:**
- Modify: `src/recruiter/api/applications.py`
- Modify: `src/recruiter/schemas/settings.py`
- Modify: `src/recruiter/schemas/application.py` (already touched in T1; verify)
- Modify: `src/recruiter/api/settings.py`
- Create: `tests/unit/test_re_enrich_endpoint.py`

- [ ] **Step 1: Add settings schema fields**

In `src/recruiter/schemas/settings.py`:

```python
class SettingsRead(BaseModel):
    ...
    enrichment_enabled: bool = False
    has_enrichment_twitter_api_key: bool = False
    has_enrichment_youtube_api_key: bool = False
    has_enrichment_stackexchange_key: bool = False
    enrichment_sources: dict[str, bool] = {}


class SettingsUpdate(BaseModel):
    ...
    enrichment_enabled: bool | None = None
    enrichment_twitter_api_key: str | None = None
    enrichment_youtube_api_key: str | None = None
    enrichment_stackexchange_key: str | None = None
    enrichment_sources: dict[str, bool] | None = None
```

- [ ] **Step 2: Update `src/recruiter/api/settings.py`**

In `_to_read`:

```python
    return SettingsRead(
        ...
        enrichment_enabled=row.enrichment_enabled,
        has_enrichment_twitter_api_key=bool(row.enrichment_twitter_api_key_enc),
        has_enrichment_youtube_api_key=bool(row.enrichment_youtube_api_key_enc),
        has_enrichment_stackexchange_key=bool(row.enrichment_stackexchange_key_enc),
        enrichment_sources=row.enrichment_sources or {},
    )
```

In `update_settings`:

```python
    if payload.enrichment_enabled is not None:
        row.enrichment_enabled = payload.enrichment_enabled
    if payload.enrichment_twitter_api_key is not None:
        row.enrichment_twitter_api_key_enc = cipher.encrypt(payload.enrichment_twitter_api_key)
    if payload.enrichment_youtube_api_key is not None:
        row.enrichment_youtube_api_key_enc = cipher.encrypt(payload.enrichment_youtube_api_key)
    if payload.enrichment_stackexchange_key is not None:
        row.enrichment_stackexchange_key_enc = cipher.encrypt(payload.enrichment_stackexchange_key)
    if payload.enrichment_sources is not None:
        row.enrichment_sources = payload.enrichment_sources
```

- [ ] **Step 3: Add the re-enrich endpoint**

Append to `src/recruiter/api/applications.py`:

```python
@router.post("/applications/{application_id}/re-enrich",
             response_model=ApplicationCreated, status_code=202)
async def re_enrich_application(
    application_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    engine: AsyncEngine = Depends(get_engine_dep),
    llm: LLMClient = Depends(get_llm),
    bus: EventBus = Depends(get_event_bus),
) -> ApplicationCreated:
    """Clear the cached enrichment bundle and re-run the pipeline starting
    at Stage.ENRICHING. The orchestrator will see `enrichment` is None
    and re-fetch fresh."""
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")

    candidate = await session.get(Candidate, app_row.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")

    app_row.enrichment = None
    app_row.stage = Stage.ENRICHING
    await session.commit()

    raw_text = ""
    if candidate.raw_extracted and isinstance(candidate.raw_extracted, dict):
        raw_text = candidate.raw_extracted.get("text", "") or ""

    routed = RoutedInput(
        kind="paste",
        text=raw_text,
        source_url=candidate.source_url,
        resume_path=candidate.resume_path,
    )
    background_tasks.add_task(
        process_application,
        application_id=application_id,
        routed=routed,
        engine=engine,
        llm=llm,
        bus=bus,
    )
    return ApplicationCreated(application_id=application_id)
```

- [ ] **Step 4: Update `_to_read` in applications.py to surface enrichment**

```python
def _to_read(app_row: Application) -> ApplicationRead:
    breakdown = ...
    return ApplicationRead(
        ...
        enrichment=app_row.enrichment,
    )
```

- [ ] **Step 5: Tests**

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_re_enrich_clears_bundle_and_returns_202(client: AsyncClient, session, mk_app):
    app = await mk_app(enrichment={"results": [{"x": 1}]})
    r = await client.post(f"/api/applications/{app.id}/re-enrich")
    assert r.status_code == 202
    await session.refresh(app)
    assert app.enrichment is None
    assert app.stage.value == "enriching"


@pytest.mark.asyncio
async def test_re_enrich_404_for_unknown_app(client: AsyncClient):
    r = await client.post("/api/applications/9999/re-enrich")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_settings_round_trip_for_enrichment_fields(client: AsyncClient):
    payload = {
        "enrichment_enabled": True,
        "enrichment_twitter_api_key": "twk",
        "enrichment_sources": {"twitter": False, "youtube": True},
    }
    r = await client.put("/api/settings", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["enrichment_enabled"] is True
    assert body["has_enrichment_twitter_api_key"] is True
    assert body["enrichment_sources"]["twitter"] is False


@pytest.mark.asyncio
async def test_application_read_includes_enrichment(client: AsyncClient, mk_app):
    app = await mk_app(enrichment={"results": [], "errors": [], "discovery_consent": False,
                                    "fetched_at": "2026-05-10T00:00:00Z",
                                    "expires_at": "2026-06-09T00:00:00Z"})
    r = await client.get(f"/api/applications/{app.id}")
    assert r.status_code == 200
    body = r.json()
    assert "enrichment" in body
    assert body["enrichment"]["results"] == []
```

> The `client` and `mk_app` fixtures should follow the existing test conventions in `tests/`.

- [ ] **Step 6: Run + commit**

```bash
uv run pytest tests/unit/test_re_enrich_endpoint.py -v
```
Expected: all 4 PASS.

```bash
git add src/recruiter/api/applications.py \
        src/recruiter/api/settings.py \
        src/recruiter/schemas/settings.py \
        src/recruiter/schemas/application.py \
        tests/unit/test_re_enrich_endpoint.py
git commit -m "feat(enrichment): add re-enrich endpoint and settings/job schema fields"
```

---

### Task 28: Settings → Enrichment tab (frontend)

**Files:**
- Create: `recruiter-frontend/src/components/settings/enrichment-tab.tsx`
- Create: `recruiter-frontend/src/components/settings/enrichment-tab.test.tsx`
- Modify: `recruiter-frontend/src/routes/settings.tsx`
- Modify: `recruiter-frontend/src/hooks/use-settings.ts` (add typings for the new fields)

Combined red+green in one task because the surface is small (master toggle, three key fields, 10-checkbox grid).

- [ ] **Step 1: Update the settings hook typings**

In `use-settings.ts` extend `SettingsRead`:

```ts
export interface SettingsRead {
  ...
  enrichment_enabled: boolean;
  has_enrichment_twitter_api_key: boolean;
  has_enrichment_youtube_api_key: boolean;
  has_enrichment_stackexchange_key: boolean;
  enrichment_sources: Record<string, boolean>;
}

export interface SettingsUpdate {
  ...
  enrichment_enabled?: boolean;
  enrichment_twitter_api_key?: string;
  enrichment_youtube_api_key?: string;
  enrichment_stackexchange_key?: string;
  enrichment_sources?: Record<string, boolean>;
}
```

- [ ] **Step 2: Failing tests**

`enrichment-tab.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { EnrichmentTab } from "./enrichment-tab";

const server = setupServer();

const ALL_SOURCES = [
  "github", "stackoverflow", "hackernews", "reddit", "mastodon",
  "bluesky", "youtube", "twitter", "devto", "blog",
];

function defaults(overrides = {}) {
  return {
    enrichment_enabled: false,
    has_enrichment_twitter_api_key: false,
    has_enrichment_youtube_api_key: false,
    has_enrichment_stackexchange_key: false,
    enrichment_sources: {},
    // unrelated fields the SettingsRead schema requires:
    default_llm_provider: "anthropic", has_anthropic_api_key: false,
    local_llm_url: null, has_local_llm_api_key: false, model_overrides: {},
    has_google_oauth_tokens: false, has_smtp_config: false,
    recruiter_name: null, recruiter_email: null, monthly_llm_spend_cap_usd: null,
    search_provider: null, search_engine_id: null, has_search_api_key: false,
    has_github_token: false,
    ...overrides,
  };
}

function mockRoutes(initial, capture) {
  let cur = initial;
  server.use(
    http.get("http://localhost:8000/api/settings", () => HttpResponse.json(cur)),
    http.put("http://localhost:8000/api/settings", async ({ request }) => {
      capture.lastBody = await request.json();
      return HttpResponse.json(cur);
    }),
  );
}

function renderTab() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <EnrichmentTab />
      <Toaster />
    </QueryClientProvider>,
  );
}

describe("EnrichmentTab", () => {
  beforeEach(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => { server.resetHandlers(); server.close(); });

  it("renders master toggle and 10 source checkboxes", async () => {
    const cap = {};
    mockRoutes(defaults(), cap);
    renderTab();
    await waitFor(() => expect(screen.getByLabelText(/Enable enrichment/i)).toBeInTheDocument());
    for (const s of ALL_SOURCES) {
      expect(screen.getByLabelText(new RegExp(s, "i"))).toBeInTheDocument();
    }
  });

  it("shows masked placeholder for keys when set on the server", async () => {
    const cap = {};
    mockRoutes(defaults({ has_enrichment_twitter_api_key: true }), cap);
    renderTab();
    const twKey = await screen.findByLabelText(/Twitter.*API key/i);
    expect(twKey).toHaveAttribute("placeholder", expect.stringContaining("(set)"));
  });

  it("toggling a source sends the new map on save", async () => {
    const cap = {};
    mockRoutes(defaults({ enrichment_enabled: true }), cap);
    renderTab();
    const twitter = await screen.findByLabelText(/twitter/i);
    await userEvent.click(twitter);  // off
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(cap.lastBody).toBeDefined());
    expect(cap.lastBody.enrichment_sources.twitter).toBe(false);
  });

  it("typing a Twitter key sends it through on save", async () => {
    const cap = {};
    mockRoutes(defaults({ enrichment_enabled: true }), cap);
    renderTab();
    const tk = await screen.findByLabelText(/Twitter.*API key/i);
    await userEvent.type(tk, "tk-abc");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(cap.lastBody).toBeDefined());
    expect(cap.lastBody.enrichment_twitter_api_key).toBe("tk-abc");
  });

  it("enabling the master toggle sends enrichment_enabled=true", async () => {
    const cap = {};
    mockRoutes(defaults(), cap);
    renderTab();
    const toggle = await screen.findByLabelText(/Enable enrichment/i);
    await userEvent.click(toggle);
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(cap.lastBody).toBeDefined());
    expect(cap.lastBody.enrichment_enabled).toBe(true);
  });
});
```

- [ ] **Step 3: Implementation**

`enrichment-tab.tsx`:

```tsx
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { ApiError } from "@/lib/api";
import { useSettings, useUpdateSettings } from "@/hooks/use-settings";

const SOURCES: { key: string; label: string; needsKey?: string; help?: string }[] = [
  { key: "github", label: "GitHub", help: "Reuses the GitHub token from the Sourcing tab." },
  { key: "stackoverflow", label: "Stack Overflow", needsKey: "stackexchange" },
  { key: "hackernews", label: "Hacker News" },
  { key: "reddit", label: "Reddit" },
  { key: "mastodon", label: "Mastodon" },
  { key: "bluesky", label: "Bluesky" },
  { key: "youtube", label: "YouTube", needsKey: "youtube" },
  { key: "twitter", label: "Twitter / X", needsKey: "twitter", help: "X API Basic tier required (~$200/month)" },
  { key: "devto", label: "Dev.to" },
  { key: "blog", label: "Blog / website (LLM summary)" },
];

export function EnrichmentTab() {
  const settings = useSettings();
  const update = useUpdateSettings();

  const [enabled, setEnabled] = useState<boolean | undefined>();
  const [twKey, setTwKey] = useState("");
  const [ytKey, setYtKey] = useState("");
  const [seKey, setSeKey] = useState("");
  const [sourceMap, setSourceMap] = useState<Record<string, boolean> | undefined>();

  // Reset typed inputs after a successful save.
  useEffect(() => {
    if (settings.data) {
      if (enabled === undefined) setEnabled(settings.data.enrichment_enabled);
      if (sourceMap === undefined) setSourceMap(settings.data.enrichment_sources ?? {});
    }
  }, [settings.data, enabled, sourceMap]);

  if (settings.isLoading) return <p>Loading…</p>;
  if (!settings.data) return <p>No settings.</p>;
  const cur = settings.data;
  const effEnabled = enabled ?? cur.enrichment_enabled;
  const effMap: Record<string, boolean> = sourceMap ?? cur.enrichment_sources ?? {};

  function toggleSource(name: string) {
    setSourceMap({ ...effMap, [name]: !(effMap[name] ?? true) });
  }

  function save() {
    const body: Record<string, unknown> = {};
    if (enabled !== undefined && enabled !== cur.enrichment_enabled) body.enrichment_enabled = enabled;
    if (twKey) body.enrichment_twitter_api_key = twKey;
    if (ytKey) body.enrichment_youtube_api_key = ytKey;
    if (seKey) body.enrichment_stackexchange_key = seKey;
    if (sourceMap !== undefined) body.enrichment_sources = sourceMap;
    update.mutate(body, {
      onSuccess: () => {
        setTwKey(""); setYtKey(""); setSeKey("");
        toast.success("Enrichment settings saved");
      },
      onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Save failed"),
    });
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="flex items-center gap-2">
        <Checkbox
          id="enrichment-enabled"
          checked={effEnabled}
          onCheckedChange={(v) => setEnabled(v === true)}
        />
        <Label htmlFor="enrichment-enabled">Enable enrichment</Label>
      </div>
      <p className="text-xs text-muted-foreground">
        Master kill switch. When off, no enrichment runs for any application.
        Per-job consent is still required for discovery and Twitter/X.
      </p>

      <div className="space-y-2">
        <Label htmlFor="tw-key">Twitter / X API key</Label>
        <Input
          id="tw-key" type="password"
          placeholder={cur.has_enrichment_twitter_api_key ? "•••••• (set)" : "X API v2 Basic bearer"}
          value={twKey} onChange={(e) => setTwKey(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">X API Basic tier required (~$200/month).</p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="yt-key">YouTube API key</Label>
        <Input
          id="yt-key" type="password"
          placeholder={cur.has_enrichment_youtube_api_key ? "•••••• (set)" : "AIza…"}
          value={ytKey} onChange={(e) => setYtKey(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">Free 10,000 units/day from Google Cloud.</p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="se-key">Stack Exchange key (optional)</Label>
        <Input
          id="se-key" type="password"
          placeholder={cur.has_enrichment_stackexchange_key ? "•••••• (set)" : "raises 300/d → 10k/d"}
          value={seKey} onChange={(e) => setSeKey(e.target.value)}
        />
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Sources</legend>
        <div className="grid grid-cols-2 gap-2">
          {SOURCES.map((s) => (
            <label key={s.key} className="flex items-start gap-2 text-sm">
              <Checkbox
                id={`source-${s.key}`}
                checked={effMap[s.key] ?? true}
                onCheckedChange={() => toggleSource(s.key)}
              />
              <span>
                <span aria-label={s.label}>{s.label}</span>
                {s.help && <span className="block text-xs text-muted-foreground">{s.help}</span>}
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <Button onClick={save} disabled={update.isPending}>
        {update.isPending ? "Saving…" : "Save"}
      </Button>
    </div>
  );
}
```

- [ ] **Step 4: Wire into `routes/settings.tsx`**

```tsx
<TabsList>
  <TabsTrigger value="llm">LLM</TabsTrigger>
  <TabsTrigger value="notifications">Notifications</TabsTrigger>
  <TabsTrigger value="sourcing">Sourcing</TabsTrigger>
  <TabsTrigger value="enrichment">Enrichment</TabsTrigger>
  <TabsTrigger value="profile">Profile</TabsTrigger>
</TabsList>
...
<TabsContent value="enrichment" className="pt-6">
  <EnrichmentTab />
</TabsContent>
```

(Add the import line.)

- [ ] **Step 5: Run + commit**

```bash
cd recruiter-frontend && npm test -- src/components/settings/enrichment-tab.test.tsx
```
Expected: all 5 PASS.

```bash
git add recruiter-frontend/src/components/settings/enrichment-tab.tsx \
        recruiter-frontend/src/components/settings/enrichment-tab.test.tsx \
        recruiter-frontend/src/routes/settings.tsx \
        recruiter-frontend/src/hooks/use-settings.ts
git commit -m "feat(frontend): Settings → Enrichment tab"
```

---

### Task 29: Job form — consent checkbox

**Files:**
- Modify: `recruiter-frontend/src/routes/jobs-new.tsx`
- Modify: `recruiter-frontend/src/routes/job-detail.tsx` (or wherever the job-edit form lives)
- Modify: `recruiter-frontend/src/routes/jobs-new.test.tsx`

- [ ] **Step 1: Update the zod schema in `jobs-new.tsx`**

```tsx
const Schema = z.object({
  title: z.string().min(1, "Title is required").max(255),
  description: z.string().min(1, "Description is required"),
  criteria: z.array(Criterion),
  enrichment_consent: z.boolean().default(false),
});
```

- [ ] **Step 2: Render the checkbox**

Above the submit button:

```tsx
<div className="flex items-start gap-2">
  <input
    type="checkbox"
    id="enrichment-consent"
    {...form.register("enrichment_consent")}
  />
  <Label htmlFor="enrichment-consent" className="text-sm leading-snug">
    Process the candidate's public technical and social presence for scoring.
    Required where applicable law (e.g., GDPR Art. 6 + 9) demands lawful basis.
  </Label>
</div>
```

- [ ] **Step 3: Add a test in `jobs-new.test.tsx`**

```tsx
it("submits enrichment_consent=true when the checkbox is ticked", async () => {
  // existing setup — fixture API mocks at /api/jobs that capture the body...
  await userEvent.click(screen.getByLabelText(/Process the candidate's public technical/i));
  // fill required fields and submit
  await userEvent.type(screen.getByLabelText(/title/i), "Rust");
  await userEvent.type(screen.getByLabelText(/description/i), "...".repeat(20));
  await userEvent.click(screen.getByRole("button", { name: /create job/i }));
  await waitFor(() => expect(captured.body.enrichment_consent).toBe(true));
});
```

- [ ] **Step 4: Mirror in the job-edit page** (`job-detail.tsx` or equivalent). Use the persisted value as the default.

- [ ] **Step 5: Run + commit**

```bash
cd recruiter-frontend && npm test -- src/routes/jobs-new.test.tsx
```
Expected: all PASS.

```bash
git add recruiter-frontend/src/routes/jobs-new.tsx \
        recruiter-frontend/src/routes/jobs-new.test.tsx \
        recruiter-frontend/src/routes/job-detail.tsx
git commit -m "feat(jobs): add enrichment_consent checkbox to job form"
```

---

### Task 30: Application detail — `<EnrichmentSection />` + re-enrich button

**Files:**
- Create: `recruiter-frontend/src/components/candidate/enrichment-section.tsx`
- Create: `recruiter-frontend/src/components/candidate/enrichment-section.test.tsx`
- Modify: `recruiter-frontend/src/routes/application-detail.tsx`
- Modify: `recruiter-frontend/src/hooks/use-application-mutations.ts` (add `useReEnrich`)

Two-section layout: high-confidence (≥0.75) at top, low-confidence (0.5) collapsed behind a toggle. Per-source rendering with confidence badge, per-signal cards, deep links. "Re-enrich now" button. Per-source error rows.

- [ ] **Step 1: Add the `useReEnrich` mutation hook**

In `use-application-mutations.ts`:

```ts
export function useReEnrich() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (applicationId: number) =>
      api(`/api/applications/${applicationId}/re-enrich`, { method: "POST" }),
    onSuccess: (_, applicationId) => {
      qc.invalidateQueries({ queryKey: queryKeys.application(applicationId) });
      toast.success("Re-enrichment queued");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Failed"),
  });
}
```

- [ ] **Step 2: Failing tests**

`enrichment-section.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { EnrichmentSection } from "./enrichment-section";

function bundle(overrides = {}) {
  return {
    fetched_at: "2026-04-30T12:00:00Z",
    expires_at: "2026-05-30T12:00:00Z",
    discovery_consent: true,
    results: [
      {
        source: "github", confidence: 1.0, discovered: false,
        profile_url: "https://github.com/alice",
        signals: [{ type: "code", summary: "rust-helper [Rust, 120 stars]", url: "https://github.com/alice/rust-helper" }],
        summary: "GitHub @alice: 42 repos.",
      },
      {
        source: "mastodon", confidence: 0.5, discovered: true,
        profile_url: "https://mastodon.social/@alice",
        signals: [{ type: "post", summary: "@alice@mastodon.social: Just shipped …" }],
        summary: "Mastodon @alice@mastodon.social.",
      },
    ],
    errors: [],
    ...overrides,
  };
}

function renderSection(props: any) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <EnrichmentSection {...props} />
      <Toaster />
    </QueryClientProvider>,
  );
}

describe("EnrichmentSection", () => {
  it("renders high-confidence findings prominently", () => {
    renderSection({ applicationId: 1, enrichment: bundle() });
    expect(screen.getByText(/GitHub @alice/i)).toBeInTheDocument();
  });

  it("collapses low-confidence findings under a toggle", async () => {
    renderSection({ applicationId: 1, enrichment: bundle() });
    expect(screen.queryByText(/Mastodon @alice/i)).not.toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: /unconfirmed match/i }));
    expect(screen.getByText(/Mastodon @alice/i)).toBeVisible();
  });

  it("shows discovered badge for low-confidence sources", async () => {
    renderSection({ applicationId: 1, enrichment: bundle() });
    await userEvent.click(screen.getByRole("button", { name: /unconfirmed match/i }));
    expect(screen.getByText(/Discovered/i)).toBeInTheDocument();
  });

  it("renders cached/expires hint", () => {
    renderSection({ applicationId: 1, enrichment: bundle() });
    expect(screen.getByText(/expires/i)).toBeInTheDocument();
  });

  it("re-enrich button calls the API and refetches", async () => {
    const server = setupServer(
      http.post("http://localhost:8000/api/applications/1/re-enrich",
        () => HttpResponse.json({ application_id: 1 }, { status: 202 })),
      http.get("http://localhost:8000/api/applications/1",
        () => HttpResponse.json({ id: 1, enrichment: bundle() })),
    );
    server.listen();
    try {
      renderSection({ applicationId: 1, enrichment: bundle() });
      await userEvent.click(screen.getByRole("button", { name: /re-enrich/i }));
      await waitFor(() => expect(screen.getByText(/queued/i)).toBeInTheDocument());
    } finally {
      server.close();
    }
  });

  it("renders per-source errors when present", () => {
    renderSection({
      applicationId: 1,
      enrichment: bundle({ errors: [{ source: "twitter", error: "401", transient: false }] }),
    });
    expect(screen.getByText(/twitter/i)).toBeInTheDocument();
    expect(screen.getByText(/401/i)).toBeInTheDocument();
  });

  it("renders nothing when enrichment is null", () => {
    const { container } = renderSection({ applicationId: 1, enrichment: null });
    expect(container.textContent).toBe("");
  });
});
```

- [ ] **Step 3: Implementation**

`enrichment-section.tsx`:

```tsx
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useReEnrich } from "@/hooks/use-application-mutations";

interface Signal {
  type: string;
  summary: string;
  url?: string | null;
  timestamp?: string | null;
}

interface Result {
  source: string;
  profile_url: string;
  confidence: number;
  discovered: boolean;
  signals: Signal[];
  summary: string;
}

interface Bundle {
  fetched_at: string;
  expires_at: string;
  discovery_consent: boolean;
  results: Result[];
  errors: { source: string; error: string; transient: boolean }[];
}

export function EnrichmentSection({
  applicationId,
  enrichment,
}: {
  applicationId: number;
  enrichment: Bundle | null;
}) {
  const reEnrich = useReEnrich();
  const [showLow, setShowLow] = useState(false);
  if (!enrichment) return null;

  const high = enrichment.results.filter((r) => r.confidence >= 0.75);
  const low = enrichment.results.filter((r) => r.confidence < 0.75);

  return (
    <section className="space-y-4 rounded border p-4">
      <header className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Enrichment</h3>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">
            cached {new Date(enrichment.fetched_at).toLocaleDateString()},
            expires {new Date(enrichment.expires_at).toLocaleDateString()}
          </span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => reEnrich.mutate(applicationId)}
            disabled={reEnrich.isPending}
          >
            {reEnrich.isPending ? "Queuing…" : "Re-enrich now"}
          </Button>
        </div>
      </header>

      {high.length === 0 && low.length === 0 && (
        <p className="text-sm text-muted-foreground">No public profiles found.</p>
      )}

      {high.map((r) => <ResultCard key={r.source} result={r} />)}

      {low.length > 0 && (
        <details open={showLow} onToggle={(e) => setShowLow((e.target as HTMLDetailsElement).open)}>
          <summary className="cursor-pointer text-sm">
            <button type="button" className="underline">
              Show {low.length} unconfirmed match{low.length > 1 ? "es" : ""}
            </button>
          </summary>
          <div className="mt-2 space-y-2">
            {low.map((r) => <ResultCard key={r.source} result={r} />)}
          </div>
        </details>
      )}

      {enrichment.errors.length > 0 && (
        <div className="border-t pt-2">
          <p className="text-xs font-medium text-muted-foreground mb-1">
            Some sources failed:
          </p>
          <ul className="space-y-1 text-xs">
            {enrichment.errors.map((e, i) => (
              <li key={i} className="text-destructive">
                <span className="font-mono">{e.source}</span>: {e.error}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function ResultCard({ result }: { result: Result }) {
  return (
    <article className="space-y-2 rounded border p-3">
      <div className="flex items-center gap-2">
        <span className="font-medium">{result.source}</span>
        <Badge variant={result.confidence >= 0.75 ? "default" : "secondary"}>
          conf {result.confidence.toFixed(2)}
        </Badge>
        {result.discovered && <Badge variant="outline">Discovered</Badge>}
        <a href={result.profile_url} target="_blank" rel="noreferrer"
           className="ml-auto text-xs underline">profile ↗</a>
      </div>
      <p className="text-sm">{result.summary}</p>
      <ul className="space-y-1">
        {result.signals.map((s, i) => (
          <li key={i} className="text-xs flex gap-2">
            <span className="text-muted-foreground uppercase">{s.type}</span>
            <span>{s.summary}</span>
            {s.url && (
              <a href={s.url} target="_blank" rel="noreferrer" className="underline">↗</a>
            )}
          </li>
        ))}
      </ul>
    </article>
  );
}
```

- [ ] **Step 4: Drop into application-detail.tsx**

In `application-detail.tsx` after `<ScoreBreakdown application={...} />`:

```tsx
import { EnrichmentSection } from "@/components/candidate/enrichment-section";
...
<ScoreBreakdown application={application.data} />
<EnrichmentSection
  applicationId={id}
  enrichment={application.data.enrichment ?? null}
/>
```

(Also extend the `ApplicationRead` typing in `use-job-applications.ts` so TypeScript knows about `enrichment`.)

- [ ] **Step 5: Run + commit**

```bash
cd recruiter-frontend && npm test -- src/components/candidate/enrichment-section.test.tsx
```
Expected: all 7 PASS.

```bash
git add recruiter-frontend/src/components/candidate/enrichment-section.tsx \
        recruiter-frontend/src/components/candidate/enrichment-section.test.tsx \
        recruiter-frontend/src/routes/application-detail.tsx \
        recruiter-frontend/src/hooks/use-application-mutations.ts \
        recruiter-frontend/src/hooks/use-job-applications.ts
git commit -m "feat(frontend): EnrichmentSection on application detail page"
```

---

### Task 31: Documentation

**Files:**
- Modify: `docs/setup.md`

- [ ] **Step 1: Append the section**

```markdown

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
```

- [ ] **Step 2: Commit**

```bash
git add docs/setup.md
git commit -m "docs(setup): document candidate enrichment + per-job consent"
```

---

### Task 32: Final verification

**Files:** none modified (a verification-only task)

- [ ] **Step 1: Full backend pytest**

```bash
uv run pytest -x
```
Expected: all PASS. Document any pre-existing failures (none expected from this work).

- [ ] **Step 2: Full frontend vitest**

```bash
cd recruiter-frontend && npm test
```
Expected: all PASS.

- [ ] **Step 3: Backend lint**

```bash
uv run ruff check src tests
```
Expected: clean.

- [ ] **Step 4: Frontend lint**

```bash
cd recruiter-frontend && npm run lint
```
Expected: clean.

- [ ] **Step 5: Browser smoke test**

Backend (`uv run uvicorn recruiter.main:app --port 8765 --reload`) and frontend (`cd recruiter-frontend && npm run dev`) running. In the browser:

1. Settings → Enrichment → tick **Enable enrichment** → Save.
2. Create a new job with consent **on** and a JD that mentions Rust.
3. Paste a resume that contains an explicit `https://github.com/<known-user>` link.
4. Open the candidate detail page. Wait for the stage to advance past `enriching`.
5. Verify the **Enrichment** section appears below **Score breakdown** and shows the GitHub finding (high-confidence, prominent).
6. Click **Re-enrich now**. Verify the spinner appears, then the section refreshes.
7. Verify the score is unchanged after re-enrichment (Decision 1 — score is computed from the resume only).
8. Disable a source in Settings → Enrichment → re-enrich → verify that source no longer appears.

If any step fails, fix and recommit; do not proceed to merge.

- [ ] **Step 6: No commit needed for this task** (verification only).

---

## Test count expectation

Track green-bar growth as tasks land. Approximate per-phase counts:

| Phase | Tests | Cumulative |
|---|---:|---:|
| T1 (models)                                   | 4   | 4   |
| T2 (registry)                                 | 6   | 10  |
| T3 (identity)                                 | 15  | 25  |
| T4-T5 (hackernews)                            | 9   | 34  |
| T6-T7 (reddit)                                | 9   | 43  |
| T8-T9 (mastodon)                              | 10  | 53  |
| T10-T11 (bluesky)                             | 9   | 62  |
| T12-T13 (devto)                               | 9   | 71  |
| T14-T15 (stackoverflow)                       | 10  | 81  |
| T16-T17 (github)                              | 10  | 91  |
| T18-T19 (youtube)                             | 9   | 100 |
| T20-T21 (twitter)                             | 10  | 110 |
| T22-T23 (blog)                                | 9   | 119 |
| T24 (discovery)                               | 8   | 127 |
| T25 (pipeline)                                | 9   | 136 |
| T26 (orchestrator + score-isolation)          | 3   | 139 |
| T27 (re-enrich endpoint + settings)           | 4   | 143 |
| T28 (Settings → Enrichment tab, frontend)     | 5   | 148 |
| T29 (job form consent)                        | 1   | 149 |
| T30 (EnrichmentSection)                       | 7   | 156 |

**Target: ~155 new tests** when T31 lands. T32 verifies the suite is fully green.

---

## Risks during implementation

The three places execution is most likely to block, and the cheapest workaround for each:

1. **Twitter/X auth flow (T20-T21)** — the X API v2 has historically been the *least* stable interface in this set. Real bearer tokens often fail in unpredictable ways (expired key, rate-limit-without-retry-after, plan downgrade). Tests rely entirely on `httpx.MockTransport`; no real network calls. If a real-world smoke test reveals a different status code or response shape than the spec assumed, just extend the error-path branches in `twitter.py::enrich` to return `None` — the orchestrator already treats provider failures as non-fatal.

2. **GitHub GraphQL contributions endpoint (deferred in T17)** — the spec mentions a GraphQL contributions calendar, but the endpoint has different rate-limit accounting and requires `read:user` scope which may not be on the existing `github_token_enc`. The plan defers this to v2 and uses REST-only `public_repos` / `followers`. If a future task wants the contributions count, add it as a separate optional GraphQL call inside `GitHubEnrichmentProvider.enrich` wrapped in a try/except so a missing scope just leaves the field empty.

3. **Identity engine cap interactions (T3)** — the spec's confidence rules are stated in plain English; the test cases pin one valid interpretation, but small variations in the order of additions could push a result above 0.8. If a test case fails after implementation, prefer adjusting the rule weighting (e.g., apply the email bonus *before* the username bonus, or hard-cap before adding the email bonus) over weakening the test. The 0.8 cap is the load-bearing invariant for "non-anchor" results.

A fourth, less likely risk: **Alembic enum-add on Postgres** (T1). `ALTER TYPE … ADD VALUE` is non-transactional in older Postgres versions; if the migration fails on a non-empty database, fall back to creating a new enum type, swapping the column, and dropping the old enum. SQLite (used in tests) is unaffected because it stores the enum as TEXT.
