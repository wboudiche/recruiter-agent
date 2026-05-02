def parse_allowed_domains(raw: str) -> list[str]:
    """Parse a comma-separated `RECRUITER_OIDC_ALLOWED_DOMAINS` value into
    a normalized (lowercase, stripped) list."""
    return [d.strip().lower() for d in raw.split(",") if d.strip()]


def is_email_allowed(email: str, allowed_domains: list[str]) -> bool:
    """Exact-domain match. v1 does NOT support subdomain wildcards —
    `acme.com` does not match `eng.acme.com`. An empty allowlist
    blocks everything (defensive default)."""
    if not email or "@" not in email:
        return False
    local, _, domain = email.partition("@")
    if not local or not domain:
        return False
    return domain.lower() in allowed_domains
