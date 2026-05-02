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
