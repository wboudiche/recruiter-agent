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
    # news.ycombinator.com/user?id=<u> — urlparse splits path/query, so check
    # path == "user" alongside an `id=` query param.
    if path == "user" and "id=" in qs:
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

    # Track usernames alongside the URL that contributed them, so a result
    # whose profile_url is itself the only anchor for its username doesn't
    # self-corroborate.
    confirmed_username_sources: dict[str, set[str]] = {}

    def _add_confirmed(un: str | None, source_url: str) -> None:
        if not un:
            return
        confirmed_username_sources.setdefault(un.lower(), set()).add(source_url.lower())

    for u in anchor_urls:
        _add_confirmed(_extract_username(u), u)
    # Provider-anchored (confidence 1.0) results add to confirmed pool too.
    for r in out:
        if r.confidence >= 1.0:
            _add_confirmed(_extract_username(r.profile_url), r.profile_url)

    anchor_email_set = {e.lower() for e in anchor_emails}
    anchor_url_set = {u.lower() for u in anchor_urls}

    # Snapshot the original (provider-supplied) confidences. All bonuses are
    # applied against this base on every pass — preventing the +0.2 username
    # bonus from re-stacking across iterations once the result has been
    # promoted past 0.5.
    original = [r.confidence for r in out]

    for _ in range(5):
        changed = False
        # Re-derive corroboration sets each pass — promotions in pass N let
        # pass N+1 cross-link further.
        confirmed_username_sources_now: dict[str, set[str]] = {
            k: set(v) for k, v in confirmed_username_sources.items()
        }
        confirmed_links: set[str] = set(anchor_url_set)
        for r in out:
            if r.confidence >= 0.8:
                un = _extract_username(r.profile_url)
                if un:
                    confirmed_username_sources_now.setdefault(un.lower(), set()).add(
                        r.profile_url.lower()
                    )
                confirmed_links.add(r.profile_url.lower())

        for idx, r in enumerate(out):
            if original[idx] >= 1.0:
                continue  # never lower or re-promote anchors

            base = original[idx]
            bonus = 0.0
            un = _extract_username(r.profile_url)

            # Rule 2: username exact-matches a confirmed username on a
            # *different* URL (corroboration must come from another source,
            # not the result corroborating itself).
            if un:
                sources = confirmed_username_sources_now.get(un.lower(), set())
                if sources - {r.profile_url.lower()}:
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
