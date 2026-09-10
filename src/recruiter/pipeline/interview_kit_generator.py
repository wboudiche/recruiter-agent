"""Interview probes generated from what scoring already doubted.

The scorer writes a rationale per criterion — "Docker/Kubernetes listed, but
no clear evidence of managing production-grade clusters". That sentence is
already the question worth asking; this turns it into one.
"""
from recruiter.llm.client import LLMClient, LLMMessage
from recruiter.schemas.interview import (
    BaselineQuestion,
    GeneratedQuestion,
    GeneratedQuestions,
)
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


_DRAFT_SYSTEM = (
    "You write a single interview question for a technical recruiter. "
    "It must probe something specific about this candidate — never generic "
    "filler, never a question the CV already answers, and never a restatement "
    "of a question already being asked. Prefer asking for a concrete story "
    "over asking whether they know a technology. Return exactly one question."
)

# A hint is free text the recruiter types. It is their own words in their own
# tool, not untrusted input, but a long paste would still crowd out the
# candidate context that makes the question good — so it is capped and clearly
# delimited rather than concatenated in raw.
_MAX_HINT_CHARS = 300


def _build_draft_prompt(
    *,
    profile: str,
    criteria: list[CriteriaItem],
    score_breakdown: list[dict] | None,
    existing_questions: list[str],
    hint: str | None,
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
    if existing_questions:
        parts.append(
            "Already being asked — do NOT repeat or rephrase any of these:\n"
            + "\n".join(f"- {q}" for q in existing_questions) + "\n"
        )
    cleaned = (hint or "").strip()[:_MAX_HINT_CHARS]
    if cleaned:
        parts.append(f"The recruiter wants to probe this specifically:\n<<<{cleaned}>>>\n")
    else:
        parts.append("The recruiter has not named a topic; choose the most valuable gap.\n")
    parts.append(
        "Return JSON with a single `questions` array holding exactly one "
        "{text, criterion}."
    )
    return "\n".join(parts)


async def draft_question(
    *,
    profile: str,
    criteria: list[CriteriaItem],
    score_breakdown: list[dict] | None,
    existing_questions: list[str],
    hint: str | None,
    llm: LLMClient,
) -> GeneratedQuestion:
    """One extra question, optionally steered by what the recruiter types."""
    prompt = _build_draft_prompt(
        profile=profile, criteria=criteria, score_breakdown=score_breakdown,
        existing_questions=existing_questions, hint=hint,
    )
    raw = await llm.chat_structured(
        messages=[LLMMessage(role="user", content=prompt)],
        schema=GeneratedQuestions,
        system=_DRAFT_SYSTEM,
        # 2048, not 512: reasoning tokens count against this budget (PR #17).
        max_tokens=2048,
        temperature=0.4,
    )
    if not raw.questions:
        raise ValueError("the model returned no question")
    return raw.questions[0]
