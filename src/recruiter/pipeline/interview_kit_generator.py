"""Interview probes generated from what scoring already doubted.

The scorer writes a rationale per criterion — "Docker/Kubernetes listed, but
no clear evidence of managing production-grade clusters". That sentence is
already the question worth asking; this turns it into one.
"""
from recruiter.llm.client import LLMClient, LLMMessage
from recruiter.schemas.interview import BaselineQuestion, GeneratedQuestions
from recruiter.schemas.job import CriteriaItem

_SYSTEM = (
    "You write interview questions for a technical recruiter. "
    "Each question probes a specific doubt about this candidate — never generic "
    "filler, never a question the CV already answers. Prefer asking for a concrete "
    "story over asking whether they know a technology. Return 3-6 questions."
)


def _build_prompt(
    *,
    profile: str,
    criteria: list[CriteriaItem],
    score_breakdown: list[dict] | None,
    baseline: list[BaselineQuestion],
) -> str:
    parts = [f"Candidate profile:\n{profile}\n"]
    if criteria:
        parts.append("Weighted criteria:\n" + "\n".join(
            f"- {c.name} (weight {c.weight}): {c.description}" for c in criteria
        ) + "\n")
    if score_breakdown:
        parts.append("Scoring found these specific doubts:\n" + "\n".join(
            f"- {row.get('criterion')} scored {row.get('score')}: {row.get('rationale')}"
            for row in score_breakdown
        ) + "\n")
    if baseline:
        parts.append(
            "These questions are already being asked — do NOT duplicate them:\n"
            + "\n".join(f"- {b.text}" for b in baseline) + "\n"
        )
    parts.append("Return JSON with a `questions` array of {text, criterion}.")
    return "\n".join(parts)


async def generate_probes(
    *,
    profile: str,
    criteria: list[CriteriaItem],
    score_breakdown: list[dict] | None,
    baseline: list[BaselineQuestion],
    llm: LLMClient,
) -> GeneratedQuestions:
    prompt = _build_prompt(
        profile=profile, criteria=criteria,
        score_breakdown=score_breakdown, baseline=baseline,
    )
    return await llm.chat_structured(
        messages=[LLMMessage(role="user", content=prompt)],
        schema=GeneratedQuestions,
        system=_SYSTEM,
        # 2048, not 512: reasoning tokens count against this budget (PR #17).
        max_tokens=2048,
        temperature=0.3,
    )
