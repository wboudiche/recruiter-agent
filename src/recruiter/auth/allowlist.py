def parse_allowed_domains(raw: str) -> list[str]:
    """Parse a comma-separated `RECRUITER_OIDC_ALLOWED_DOMAINS` value into
    a normalized (lowercase, stripped) list."""
    return [d.strip().lower() for d in raw.split(",") if d.strip()]


def is_email_allowed(email: str, allowed_domains: list[str]) -> bool:
    """Exact-domain match. v1 does NOT support subdomain wildcards —
    `acme.com` does not match `eng.acme.com`. An empty allowlist
    blocks everything (defensive default — fail closed).

    Uses `rpartition('@')` per RFC 5321: the rightmost `@` is the
    local/domain separator. An embedded `@` in the resulting domain
    indicates a malformed address; reject it.
    """
    # Fail-closed: empty allowlist blocks everything. Explicit guard so
    # a future refactor can't silently flip the policy.
    if not allowed_domains:
        return False
    if not email or "@" not in email:
        return False
    local, _, domain = email.rpartition("@")
    if not local or not domain or "@" in domain:
        return False
    return domain.lower() in allowed_domains
