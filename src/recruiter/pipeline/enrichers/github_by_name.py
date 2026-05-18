"""Find a GitHub profile that plausibly belongs to a named candidate.

Used as a fallback enrichment path for LinkedIn-sourced candidates whose
profile body we can't scrape directly. Strategy:

  1. Query GitHub's `/search/users` (via the existing GitHubSearchClient)
     for the candidate's name.
  2. For each top result, fetch the full GitHub profile (`fetch_github`)
     and compare its `Name:` line against the candidate's name with a
     conservative token-overlap heuristic.
  3. Return the URL of the first confident match, or None.

The heuristic is intentionally strict — false-positive matches would
overwrite an otherwise-valid candidate row with the wrong person's data.
Single-token candidate names (e.g. "Andrej") are rejected outright
because they collide far too often.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from recruiter.crypto import settings_cipher
from recruiter.models import SettingsRow
from recruiter.pipeline.fetchers.github import fetch_github
from recruiter.sourcing.github import GitHubSearchClient
from recruiter.sourcing.provider import SearchError

logger = logging.getLogger(__name__)


def _normalize_name(name: str) -> list[str]:
    """Lowercase + strip accents + split on non-alphanumerics. Tokens of
    length 1 are dropped (initials make false positives explode)."""
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    tokens = re.split(r"[^a-zA-Z0-9]+", ascii_only.lower())
    return [t for t in tokens if len(t) >= 2]


def name_matches(
    candidate_name: str | None,
    github_name: str | None,
    *,
    github_login: str | None = None,
) -> bool:
    """Token-overlap match between a candidate name and a GitHub identity.

    Both the GitHub `name` field AND the `login` contribute tokens. This
    is important because many people stash their surname in their login
    (e.g. Karpathy's name is just "Andrej" but his login is "karpathy").
    The candidate name must have at least 2 alphanumeric tokens — single
    first-names collide too often. At least 2 tokens must appear in both
    the candidate set and the combined GitHub set.

    Examples of TRUE: ("Sergey Stepanyan", "Sergey Stepanyan", None) /
    ("Andrej Karpathy", "Andrej", "karpathy") /
    ("Marie Laval", "Marie LAVAL", None).
    Examples of FALSE: ("Andrej", "Andrej Karpathy", "karpathy") (single-
    token candidate) / ("Sergey Stepanyan", "Sergey Vasiliev", "svas")
    (only one overlapping token).
    """
    if not candidate_name:
        return False
    cand = set(_normalize_name(candidate_name))
    if len(cand) < 2:
        return False
    gh: set[str] = set()
    if github_name:
        gh.update(_normalize_name(github_name))
    if github_login:
        gh.update(_normalize_name(github_login))
    if not gh:
        return False
    return len(cand & gh) >= 2


def _parse_github_identity(profile_text: str) -> tuple[str | None, str | None]:
    """Pull `(name, login)` from the rendered GitHub profile body."""
    name: str | None = None
    login: str | None = None
    for line in profile_text.splitlines():
        if line.startswith("Name: ") and name is None:
            name = line[len("Name: "):].strip() or None
        elif line.startswith("GitHub login: ") and login is None:
            login = line[len("GitHub login: "):].strip() or None
        if name is not None and login is not None:
            break
    return name, login


async def find_github_url_for_name(
    name: str,
    *,
    settings: SettingsRow | None,
    limit: int = 5,
) -> str | None:
    """Search GitHub for `name`, fetch each result's full profile, return
    the URL of the first plausible match (or None).

    Strict by design — see module docstring. Network/auth failures from
    GitHub return None silently so the caller can fall back to the
    awaiting-paste flow without surfacing a confusing error to the user.
    """
    if not name or not name.strip():
        return None
    if len(_normalize_name(name)) < 2:
        # Single-token names: skip outright (would match thousands of users).
        return None

    token = None
    if settings is not None and settings.github_token_enc:
        token = settings_cipher().decrypt(settings.github_token_enc)

    client = GitHubSearchClient(token=token)
    try:
        try:
            results = await client.search_users(name, limit)
        except SearchError as exc:
            logger.info("github search failed during enrichment: %s", exc)
            return None
    finally:
        await client.aclose()

    for r in results:
        url = r.url
        if not url:
            continue
        try:
            parsed = await fetch_github(url, token=token)
        except Exception as exc:  # network / 404 / parse — keep walking
            logger.info("fetch_github(%s) failed during enrichment: %s", url, exc)
            continue
        github_name, github_login = _parse_github_identity(parsed.text)
        if name_matches(name, github_name, github_login=github_login):
            return url
    return None
