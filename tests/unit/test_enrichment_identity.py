import pytest

from recruiter.enrichment.identity import consolidate
from recruiter.enrichment.provider import EnrichmentResult, EnrichmentSignal


def _result(
    source: str,
    *,
    confidence: float,
    profile_url: str,
    signals=None,
    summary="x",
) -> EnrichmentResult:
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
    out = consolidate(
        [confirmed_gh, masto],
        anchor_urls=["https://github.com/alice"],
        anchor_emails=[],
    )
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
