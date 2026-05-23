from recruiter.llm.client import LLMClient, LLMMessage
from recruiter.schemas.job import CriteriaItem
from recruiter.schemas.job_suggest import SuggestedSearchQuery

_SYSTEM = """You are a sourcing expert. Given a job description, weighted criteria, and the sources the recruiter wants to search, propose ONE concise search query that surfaces candidates likely to match.

Source-specific conventions:
- linkedin: short phrase of the most discriminating skills + seniority + location. Avoid Boolean operators (LinkedIn handles natural language well). Example: senior devops kubernetes Tunisia
- github: keyword search optimized for the GitHub user/code search. Use language: or location: filters where applicable. Example: language:python location:Paris pytorch
- web: Google-style Boolean. Use quoted phrases for must-have skills and a site: filter when the role is clearly platform-specific. Example: "senior data scientist" pytorch "MLOps" -junior

If multiple sources are selected, return ONE query that works reasonably across them — prefer the LinkedIn style (least restrictive operators). Keep it under 200 characters. Return JSON only.
"""


def _build_prompt(
    *,
    title: str | None,
    description: str,
    criteria: list[CriteriaItem],
    sources: list[str],
) -> str:
    head = f"Job title: {title}\n\n" if title else ""
    crits = ""
    if criteria:
        crits = "Weighted criteria:\n" + "\n".join(
            f"- {c.name} (weight {c.weight}): {c.description}" for c in criteria
        ) + "\n\n"
    return (
        f"{head}"
        f"Job description:\n{description}\n\n"
        f"{crits}"
        f"Sources selected: {', '.join(sources)}\n\n"
        f"Return JSON with a single `query` field."
    )


async def suggest_search_query(
    *,
    title: str | None,
    description: str,
    criteria: list[CriteriaItem],
    sources: list[str],
    llm: LLMClient,
) -> str:
    user = _build_prompt(
        title=title, description=description, criteria=criteria, sources=sources,
    )
    raw = await llm.chat_structured(
        messages=[LLMMessage(role="user", content=user)],
        schema=SuggestedSearchQuery,
        system=_SYSTEM,
        max_tokens=512,
        temperature=0.2,
    )
    return raw.query.strip()
