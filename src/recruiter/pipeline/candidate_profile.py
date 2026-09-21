"""The candidate as a prompt sees them.

Scoring hands the LLM the whole structured candidate; interview-question
generation used to hand it `summary` alone, which is why its probes drifted
towards things the CV already answers. Both now read from here.
"""
from typing import Any

from recruiter.models import Candidate
from recruiter.schemas.candidate import EducationItem, ExperienceItem, LinkItem
from recruiter.schemas.extraction import ExtractedCandidate

# Enough enrichment to steer a question, not so much that it crowds out the
# candidate's own history. Ordered by the provider's own confidence.
_MAX_ENRICHMENT_SUMMARIES = 6


def to_extracted(c: Candidate) -> ExtractedCandidate:
    """The persisted candidate as the extraction schema the prompts expect."""
    return ExtractedCandidate(
        full_name=c.full_name,
        email=c.email,
        phone=c.phone,
        location=c.location,
        headline=c.headline,
        summary=c.summary,
        skills=c.skills or [],
        experience=[ExperienceItem(**e) for e in (c.experience or [])],
        education=[EducationItem(**e) for e in (c.education or [])],
        links=[LinkItem(**link) for link in (c.links or [])],
    )


def _enrichment_lines(enrichment: dict[str, Any] | None) -> list[str]:
    """One recruiter-facing line per enriched source, best confidence first.

    Each provider already writes a one-paragraph `summary` for humans; that
    is exactly the register a question should be built from, so it is reused
    rather than re-derived from raw signals.
    """
    results = (enrichment or {}).get("results") or []
    ranked = sorted(
        (r for r in results if (r or {}).get("summary")),
        key=lambda r: r.get("confidence") or 0.0,
        reverse=True,
    )
    return [
        f"- {r.get('source')}: {r['summary']}"
        for r in ranked[:_MAX_ENRICHMENT_SUMMARIES]
    ]


def profile_text(c: Candidate, *, enrichment: dict[str, Any] | None) -> str:
    """A readable profile block for a prompt.

    Plain prose rather than a JSON dump: these prompts ask for interview
    questions, and a model writing questions reads a profile better than it
    reads a serialised object. Empty sections are omitted entirely so a
    sparsely extracted candidate does not arrive as a wall of "None".
    """
    parts: list[str] = []
    headline = " · ".join(x for x in (c.full_name, c.headline, c.location) if x)
    if headline:
        parts.append(headline)
    if c.summary:
        parts.append(c.summary)
    if c.skills:
        parts.append("Skills: " + ", ".join(c.skills))

    for item in c.experience or []:
        where = " at ".join(x for x in (item.get("title"), item.get("company")) if x)
        when = " – ".join(x for x in (item.get("start"), item.get("end")) if x)
        line = f"- {where}" + (f" ({when})" if when else "")
        if item.get("description"):
            line += f": {item['description']}"
        parts.append(line)

    for item in c.education or []:
        line = " · ".join(
            str(x) for x in (item.get("degree"), item.get("school"), item.get("year")) if x
        )
        if line:
            parts.append(f"- {line}")

    lines = _enrichment_lines(enrichment)
    if lines:
        parts.append("Found elsewhere online:")
        parts.extend(lines)

    return "\n".join(parts) or (c.full_name or "")
