# src/recruiter/pipeline/criteria_suggester.py
from recruiter.llm.client import LLMClient, LLMMessage
from recruiter.schemas.job import CriteriaItem
from recruiter.schemas.job_suggest import SuggestedCriteria

_MIN_COUNT = 3
_MAX_COUNT = 6

_SYSTEM = """You are a recruiting expert. Given a job title and description, propose between 3 and 6 weighted scoring criteria a recruiter can use to evaluate candidates. Each criterion has:
- name: short, max 128 characters (e.g. "Java expertise")
- weight: float in [0, 1]; weights across all criteria must sum to 1.0
- description: one or two sentences explaining what evidence to look for

Avoid overlapping criteria. Avoid generic filler ("good communicator") unless the job description specifically emphasizes it. Output JSON only matching the requested schema."""


def _build_user_prompt(title: str | None, description: str, *, count_hint: str = "") -> str:
    head = f"Job title: {title}\n\n" if title else ""
    tail = f"\n\n{count_hint}" if count_hint else ""
    return (
        f"{head}Job description:\n{description}\n\n"
        f"Return between {_MIN_COUNT} and {_MAX_COUNT} criteria as the structured JSON.{tail}"
    )


def _normalize_weights(items: list[CriteriaItem]) -> list[CriteriaItem]:
    """Scale weights to sum to exactly 1.0 (within float epsilon)."""
    total = sum(c.weight for c in items)
    if total <= 0:
        # Degenerate — fall back to equal weights.
        equal = round(1.0 / len(items), 2)
        scaled = [c.model_copy(update={"weight": equal}) for c in items]
    else:
        scaled = [
            c.model_copy(update={"weight": round(c.weight / total, 2)}) for c in items
        ]
    # Push residual onto the largest weight so the final sum equals 1.0.
    residual = round(1.0 - sum(c.weight for c in scaled), 2)
    if residual != 0.0:
        idx = max(range(len(scaled)), key=lambda i: scaled[i].weight)
        bumped = scaled[idx].model_copy(update={"weight": round(scaled[idx].weight + residual, 2)})
        scaled[idx] = bumped
    return scaled


async def suggest_criteria(
    *,
    title: str | None,
    description: str,
    llm: LLMClient,
) -> list[CriteriaItem]:
    """Return 3-6 weighted criteria suggested by the LLM for this JD.

    Re-prompts once if the LLM returns the wrong number of criteria. Raises
    ValueError if still off after the retry.
    """
    user = _build_user_prompt(title, description)
    raw = await llm.chat_structured(
        messages=[LLMMessage(role="user", content=user)],
        schema=SuggestedCriteria,
        system=_SYSTEM,
        max_tokens=2048,
        temperature=0.2,
    )

    if not (_MIN_COUNT <= len(raw.criteria) <= _MAX_COUNT):
        # One retry with explicit count instruction.
        retry_user = _build_user_prompt(
            title, description,
            count_hint=f"You must return exactly between {_MIN_COUNT} and {_MAX_COUNT} criteria.",
        )
        raw = await llm.chat_structured(
            messages=[LLMMessage(role="user", content=retry_user)],
            schema=SuggestedCriteria,
            system=_SYSTEM,
            max_tokens=2048,
            temperature=0.2,
        )
        if not (_MIN_COUNT <= len(raw.criteria) <= _MAX_COUNT):
            raise ValueError(
                f"LLM returned {len(raw.criteria)} criteria after retry; "
                f"expected {_MIN_COUNT}-{_MAX_COUNT}"
            )

    items = [
        CriteriaItem(name=c.name, weight=c.weight, description=c.description)
        for c in raw.criteria
    ]
    return _normalize_weights(items)
