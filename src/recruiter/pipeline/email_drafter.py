import json

from recruiter.llm.client import LLMClient, LLMMessage
from recruiter.schemas.extraction import ExtractedCandidate
from recruiter.schemas.notification import DraftedEmail, Slot

_SYSTEM = """You write concise, warm interview-invitation emails.

The recruiter has reviewed and validated the candidate. Your job is to draft an email
that (1) introduces the role briefly, (2) highlights one or two specific things from
the candidate's profile that fit the role, (3) proposes the listed time slots, and
(4) ends with a clear call to action.

Stay under 200 words. First-person, signed by the recruiter. No links, no signatures
beyond the recruiter's name.

Output JSON only matching the requested schema."""


async def draft_email(
    *,
    recruiter_name: str,
    recruiter_email: str,
    company: str,
    job_title: str,
    candidate: ExtractedCandidate,
    slots: list[Slot],
    llm: LLMClient,
) -> DraftedEmail:
    slots_payload = [
        {"start": s.start.isoformat(), "end": s.end.isoformat()} for s in slots
    ]
    user = (
        f"Recruiter: {recruiter_name} <{recruiter_email}>\n"
        f"Company: {company}\n"
        f"Role: {job_title}\n\n"
        f"Candidate:\n{json.dumps(candidate.model_dump(), ensure_ascii=False, indent=2)}\n\n"
        f"Proposed time slots (UTC):\n{json.dumps(slots_payload, indent=2)}\n\n"
        "Draft the email."
    )
    return await llm.chat_structured(
        messages=[LLMMessage(role="user", content=user)],
        schema=DraftedEmail,
        system=_SYSTEM,
        max_tokens=1024,
        temperature=0.3,
    )
