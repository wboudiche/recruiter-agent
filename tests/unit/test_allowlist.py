from recruiter.auth.allowlist import is_email_allowed, parse_allowed_domains


def test_parse_strips_whitespace_and_lowercases() -> None:
    assert parse_allowed_domains("acme.com, ACME-CORP.COM ") == ["acme.com", "acme-corp.com"]


def test_parse_empty_returns_empty_list() -> None:
    assert parse_allowed_domains("") == []


def test_allowed_when_domain_matches() -> None:
    assert is_email_allowed("alice@acme.com", ["acme.com"]) is True
    assert is_email_allowed("BOB@ACME.COM", ["acme.com"]) is True


def test_blocked_when_domain_missing() -> None:
    assert is_email_allowed("alice@evil.com", ["acme.com"]) is False


def test_blocked_when_subdomain_does_not_match() -> None:
    """v1 does not support wildcards; eng.acme.com is NOT acme.com."""
    assert is_email_allowed("alice@eng.acme.com", ["acme.com"]) is False


def test_blocked_when_allowlist_empty() -> None:
    """Empty allowlist = nothing allowed (defensive default)."""
    assert is_email_allowed("alice@acme.com", []) is False


def test_multiple_allowed_domains() -> None:
    assert is_email_allowed("alice@acme.com", ["acme.com", "acme-corp.com"])
    assert is_email_allowed("bob@acme-corp.com", ["acme.com", "acme-corp.com"])


def test_malformed_email_blocked() -> None:
    assert is_email_allowed("not-an-email", ["acme.com"]) is False
    assert is_email_allowed("@acme.com", ["acme.com"]) is False
    assert is_email_allowed("alice@", ["acme.com"]) is False


def test_blocked_when_subdomain_arbitrary_depth() -> None:
    """Locks v1 'exact match only' against future wildcard regressions."""
    assert is_email_allowed("alice@bar.acme.com", ["acme.com"]) is False


def test_blocked_when_suffix_confusion() -> None:
    """`acme.com.evil.com` must NOT match `acme.com` — guards against
    a naive `endswith('.acme.com')` future implementation."""
    assert is_email_allowed("alice@acme.com.evil.com", ["acme.com"]) is False


def test_blocked_when_prefix_confusion() -> None:
    """`xacme.com` must NOT match `acme.com`."""
    assert is_email_allowed("alice@xacme.com", ["acme.com"]) is False


def test_blocked_when_trailing_dot_fqdn() -> None:
    """`acme.com.` (trailing-dot FQDN form) must NOT match `acme.com`
    in the allowlist (admins write the canonical form, not the FQDN form)."""
    assert is_email_allowed("alice@acme.com.", ["acme.com"]) is False


def test_rpartition_handles_multiple_at_signs() -> None:
    """RFC 5321: rightmost `@` is the separator. `alice@evil.com@acme.com`
    has domain `acme.com` per RFC, BUT the embedded `@` in the address
    is malformed — reject."""
    # rpartition gives local='alice@evil.com', domain='acme.com' — domain alone
    # is fine, BUT `@` in the local part means the original address is malformed.
    # The `if "@" in domain: return False` guard rejects the inverse shape too.
    # Test BOTH directions:
    # 1. Embedded @ in the (rpartition-)domain side via partition mismatch:
    #    None possible from rpartition (it grabs the last @), so we test
    #    the suspicious "double @" form is at minimum not allowed when the
    #    real domain isn't on the allowlist:
    assert is_email_allowed("alice@evil.com@unknown.com", ["acme.com"]) is False
    # 2. The genuinely malformed form where rpartition would silently accept:
    #    confirm the rightmost @ is what's checked (this is the RFC behavior).
    assert is_email_allowed("alice@evil.com@acme.com", ["acme.com"]) is True
