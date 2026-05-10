from datetime import timedelta

import pytest

from recruiter.enrichment.pipeline import BUNDLE_TTL, enrich
from recruiter.enrichment.provider import (
    _REGISTRY,
    EnrichmentBundle,
    EnrichmentHint,
    EnrichmentResult,
    EnrichmentSignal,
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
    """consent=False -> no discovery query, only candidate.links are used."""
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
    should treat that as a 1.0 anchor - not require corroboration."""
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
