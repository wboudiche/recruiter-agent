from datetime import UTC

from recruiter.enrichment.provider import (
    _REGISTRY,
    EnrichmentBundle,
    EnrichmentHint,
    EnrichmentResult,
    EnrichmentSignal,
    register,
    resolve_all,
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
    from datetime import datetime
    b = EnrichmentBundle(
        fetched_at=datetime.now(UTC),
        expires_at=datetime.now(UTC),
        discovery_consent=True,
        results=[],
        errors=[{"source": "twitter", "error": "401", "transient": False}],
    )
    assert b.discovery_consent is True
    assert b.errors[0]["source"] == "twitter"
