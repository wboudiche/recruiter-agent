import json

from recruiter.llm.client import LLMClient, LLMMessage
from recruiter.schemas.extraction import ExtractedCandidate, ScoreResult
from recruiter.schemas.job import CriteriaItem

_SYSTEM = """You are a recruiting evaluator. Score the candidate against the job description and weighted criteria.

For each criterion, return a 0-100 score and a one-sentence rationale. The overall score is a weighted average,
rounded to an integer. Be honest and specific. Avoid generic statements. If the candidate is missing evidence
for a criterion, score low and say what is missing.

Output JSON only matching the requested schema."""


async def score_candidate(
    *,
    job_title: str,
    job_description: str,
    criteria: list[CriteriaItem],
    candidate: ExtractedCandidate,
    llm: LLMClient,
) -> ScoreResult:
    criteria_payload = [c.model_dump() for c in criteria]
    candidate_payload = candidate.model_dump()
    user = (
        f"Job title: {job_title}\n\n"
        f"Job description:\n{job_description}\n\n"
        f"Weighted criteria (weights sum to 1.0):\n{json.dumps(criteria_payload, ensure_ascii=False, indent=2)}\n\n"
        f"Candidate:\n{json.dumps(candidate_payload, ensure_ascii=False, indent=2)}\n\n"
        "Return the structured score JSON."
    )
    return await llm.chat_structured(
        messages=[LLMMessage(role="user", content=user)],
        schema=ScoreResult,
        system=_SYSTEM,
        max_tokens=4096,
        temperature=0.0,
    )
