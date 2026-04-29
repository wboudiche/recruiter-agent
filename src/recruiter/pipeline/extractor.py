from recruiter.llm.client import LLMClient, LLMMessage
from recruiter.schemas.extraction import ExtractedCandidate

_SYSTEM = """You are a resume and profile parser. Given raw text from a resume, profile, or web page,
extract structured information about the candidate. Be conservative — leave fields null/empty when
not clearly stated. Do not invent skills or experience. Output JSON only matching the requested schema."""


async def extract_candidate(*, text: str, llm: LLMClient) -> ExtractedCandidate:
    if not text.strip():
        return ExtractedCandidate()
    user = f"Raw candidate text:\n\n{text}\n\nReturn the structured JSON."
    return await llm.chat_structured(
        messages=[LLMMessage(role="user", content=user)],
        schema=ExtractedCandidate,
        system=_SYSTEM,
        max_tokens=4096,
        temperature=0.0,
    )
