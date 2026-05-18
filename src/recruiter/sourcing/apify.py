"""LinkedIn profile fetcher via Apify's `dev_fusion/linkedin-profile-scraper` actor.

A commercial alternative to the Playwright path. Reliable (Apify handles
anti-bot themselves) but costs ~$0.01/profile. Wired as an opt-in: when
`settings.apify_api_key_enc` is non-null, LinkedIn URLs route here first
and fall back to Playwright on any error.

The actor returns structured JSON. We render that JSON to clean text
and feed it through the existing LLM extractor — keeps the rest of the
pipeline unchanged. (Proxycurl was this slot's previous tenant; it shut
down in 2025 after a LinkedIn lawsuit.)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from recruiter.pipeline.parsers.text import ParsedContent

logger = logging.getLogger(__name__)

# Run-sync-get-dataset-items lets us POST a config and get back the
# dataset items inline without polling. Apify's URL-safe separator for
# the `username/actor` identifier is `~`, so we substitute it from the
# user-facing `username/actor` form.
DEFAULT_ACTOR_ID = "dev_fusion/linkedin-profile-scraper"


def _build_api_url(actor_id: str) -> str:
    slug = actor_id.strip().replace("/", "~")
    return f"https://api.apify.com/v2/acts/{slug}/run-sync-get-dataset-items"


def _as_str(value: Any) -> str:
    """Coerce an Apify field to a plain string.

    Different actors emit the same logical field as either a bare
    string OR a dict like `{"name": "Acme", "url": "..."}` or
    `{"text": "Senior Eng"}`. Treating everything as strings would
    crash on the dict variants. This helper handles both:

      - string → stripped string
      - dict   → first non-empty value under common keys (`name`,
                 `text`, `title`, `value`)
      - other  → ""
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for k in ("name", "text", "title", "value", "label"):
            v = value.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


def _pick(entry: dict, *keys: str) -> str:
    """Return the first non-empty stringified value across `keys`."""
    for k in keys:
        v = _as_str(entry.get(k))
        if v:
            return v
    return ""


def _date_from_apify(value: Any) -> str:
    """Apify emits dates either as YYYY-MM strings or as small dicts
    like `{"month": 6, "year": 2021}` or `{"text": "Jun 2021"}`.
    Normalise to a string."""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        # Prefer a pre-formatted text field if present.
        text = _as_str(value)
        if text:
            return text
        # Fall back to month/year decomposition.
        y = value.get("year")
        m = value.get("month")
        if y and m:
            try:
                return f"{int(y)}-{int(m):02d}"
            except (TypeError, ValueError):
                return ""
        if y:
            return str(y)
    return ""


def _stringify_skill(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        # Apify wraps skills as {name: "...", endorsementCount: ...}
        return _pick(item, "name", "title", "skill")
    return ""


def _render_profile_text(data: dict) -> str:
    """Render Apify's JSON into a clean text block the LLM can
    extract from. Mirrors the shape we'd otherwise get from a Playwright
    scrape — headline first, then sections.

    Defensive against per-actor shape variation: every leaf field is
    coerced through `_as_str`, which handles both bare strings and the
    common `{name|text|title|value: "..."}` dict variants.
    """
    lines: list[str] = []
    name = _pick(data, "fullName", "name")
    if not name:
        first = _pick(data, "firstName")
        last = _pick(data, "lastName")
        name = " ".join(p for p in (first, last) if p)
    if name:
        lines.append(f"Name: {name}")
    headline = _pick(data, "headline", "title", "subtitle")
    if headline:
        lines.append(f"Headline: {headline}")
    summary = _pick(data, "summary", "about", "description")
    if summary:
        lines.append(f"Summary: {summary}")

    # Apify doesn't have a single top-level "location" field; derive
    # from common alternatives so the extractor downstream has
    # something to lock onto.
    loc_parts: list[str] = []
    for k in (
        "addressWithCountry", "addressWithoutCountry", "addressCountryOnly",
        "city", "country", "geoLocationName", "location",
    ):
        v = _as_str(data.get(k))
        if v and v not in loc_parts:
            loc_parts.append(v)
    if loc_parts:
        lines.append("Location: " + ", ".join(loc_parts))

    exps = data.get("experiences") or data.get("positions") or []
    if exps:
        lines.append("")
        lines.append("Experience:")
        for e in exps:
            if not isinstance(e, dict):
                continue
            title = _pick(e, "title", "position", "role")
            company = _pick(e, "companyName", "company", "organization")
            start = _date_from_apify(
                e.get("jobStartedOn") or e.get("startDate") or e.get("start")
            )
            end_raw = e.get("jobEndedOn") or e.get("endDate") or e.get("end")
            end = _date_from_apify(end_raw) if end_raw else "present"
            descr = _pick(e, "jobDescription", "description", "summary")
            location = _pick(e, "jobLocation", "location")
            head = " · ".join(s for s in (title, company) if s)
            dates = f"{start} – {end}" if start else end
            lines.append(f"- {head} ({dates})")
            if location:
                lines.append(f"  {location}")
            if descr:
                lines.append(f"  {descr}")

    edu = data.get("educations") or data.get("education") or []
    if edu:
        lines.append("")
        lines.append("Education:")
        for it in edu:
            if not isinstance(it, dict):
                continue
            school = _pick(it, "school", "institution", "schoolName")
            degree = _pick(it, "degree", "degreeName")
            field = _pick(it, "fieldOfStudy", "field", "fieldName")
            start = _date_from_apify(
                it.get("startDate") or it.get("start")
            )
            end = _date_from_apify(
                it.get("endDate") or it.get("end")
            )
            head = " · ".join(s for s in (degree, field, school) if s)
            dates = f"{start} – {end}" if start and end else (end or start or "")
            lines.append(f"- {head}" + (f" ({dates})" if dates else ""))

    raw_skills = data.get("skills") or []
    skill_names = [s for s in (_stringify_skill(x) for x in raw_skills) if s]
    if skill_names:
        lines.append("")
        lines.append("Skills: " + ", ".join(skill_names))

    return "\n".join(lines)


class ApifyError(Exception):
    """Raised when Apify returns a definitive failure (bad token, out
    of credits, profile not found, actor error). The caller falls
    through to the Playwright path on any of these."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


async def fetch_profile_via_apify(
    url: str,
    *,
    api_key: str,
    actor_id: str = DEFAULT_ACTOR_ID,
    timeout: float = 90.0,
) -> ParsedContent:
    """Run Apify's profile-scraper actor on a single LinkedIn URL and
    return the rendered text. Raises ApifyError on auth/billing/not-
    found / actor failures so the caller knows to fall through to the
    local fetcher.

    `actor_id` is the user-facing `username/actor-name` slug; defaults
    to `dev_fusion/linkedin-profile-scraper` but is configurable
    because some actors (including the default) restrict API access
    by plan tier and free-plan users need to point at a different one.

    The default 90s timeout covers Apify's typical 5-20s actor startup
    + 5-10s scrape window. They sometimes spike on cold start; we'd
    rather wait than give up and burn the credit for nothing.
    """
    if not api_key:
        raise ApifyError("no apify api key configured")
    if "linkedin.com" not in url.lower():
        raise ApifyError(f"not a linkedin url: {url}")

    api_url = _build_api_url(actor_id or DEFAULT_ACTOR_ID)
    # Different LinkedIn-profile-scraper actors expect different
    # input shapes for the same logical "list of profile URLs":
    #
    #   - dev_fusion, curious_coder:  profileUrls: ["url", ...]
    #   - supreme_coder:              urls: [{"url": "url"}, ...]
    #   - some others:                startUrls: [{"url": "url"}, ...]
    #
    # Sending all three in one payload makes the same code work across
    # actor variants without per-actor config — unknown fields are
    # silently ignored by each actor's input validator.
    payload = {
        "profileUrls": [url],
        "urls": [{"url": url}],
        "startUrls": [{"url": url}],
    }
    params = {"token": api_key, "timeout": "60"}

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            r = await client.post(api_url, params=params, json=payload)
        except httpx.HTTPError as exc:
            raise ApifyError(f"apify network error: {exc}") from exc

    if r.status_code == 401:
        raise ApifyError("apify: bad api token", status_code=401)
    if r.status_code == 402:
        raise ApifyError("apify: out of credits", status_code=402)
    if r.status_code == 404:
        raise ApifyError(
            f"apify: actor {actor_id!r} not found — check the slug",
            status_code=404,
        )
    if r.status_code == 429:
        raise ApifyError("apify: rate limited", status_code=429)
    if r.status_code >= 500:
        raise ApifyError(
            f"apify: server error {r.status_code}", status_code=r.status_code,
        )
    # Both 200 and 201 may come back — some actors emit 201 with the
    # dataset inline. We accept either and inspect the payload shape.
    if r.status_code not in (200, 201):
        raise ApifyError(
            f"apify: unexpected status {r.status_code}: {r.text[:200]}",
            status_code=r.status_code,
        )

    try:
        items = r.json()
    except Exception as exc:
        raise ApifyError(f"apify: invalid JSON: {exc}") from exc

    if not isinstance(items, list) or not items:
        # Apify returns [] when the actor ran but produced no dataset
        # entries — usually means the URL didn't resolve to a real
        # profile (404 on their side, or rate-blocked).
        raise ApifyError("apify: no profile data returned")

    data = items[0]
    if not isinstance(data, dict):
        raise ApifyError(f"apify: unexpected item shape: {type(data).__name__}")

    # Some actors return an in-band error in place of profile data
    # (e.g., dev_fusion/linkedin-profile-scraper on the free Apify
    # plan: status 201 + `[{"error": "Users on the free Apify plan…"}]`).
    # Surface that clearly so the caller / user can act.
    err = data.get("error")
    if err and not data.get("fullName") and not data.get("firstName"):
        if isinstance(err, dict):
            err_msg = err.get("message") or str(err)
        else:
            err_msg = str(err)
        raise ApifyError(f"apify actor reported error: {err_msg}")

    text = _render_profile_text(data)
    return ParsedContent(
        text=text,
        metadata={"source_url": url, "provider": "apify"},
    )
