"""Draft a starting question set for an interview template.

Templates are organisation-wide, so the model works from what the admin
gives it: the template's name, description and kind, and optionally an
existing job whose ad says what the speciality covers. Nothing is stored;
the editor appends the result for the admin to keep, edit or delete.
"""
from recruiter.llm.client import LLMClient, LLMMessage
from recruiter.pipeline.interview_kit_generator import _MAX_ROLE_CHARS, _clean, _fenced
from recruiter.schemas.interview_template import (
    SuggestedTemplateQuestion,
    SuggestedTemplateQuestions,
    TemplateKind,
)

_MIN_COUNT = 5
_MAX_COUNT = 8

_COMMON = (
    "You write the fixed questions of a reusable interview template: every "
    "candidate interviewed with this template is asked them, so they must not "
    "depend on one person's CV. Each question stands alone and can be answered "
    f"in a few minutes. Return between {_MIN_COUNT} and {_MAX_COUNT} questions; "
    "for each, `criterion` names in a few words the skill or theme it tests."
)

_SYSTEM: dict[str, str] = {
    "technical": (
        f"{_COMMON} This is a technical interview for the speciality the "
        "template names. Probe its core skills by asking for a concrete story, "
        "a decision and its trade-offs, or how they would approach a realistic "
        "problem — never \"do you know X\". No questions about motivation, "
        "salary, notice period or culture fit: another round covers those."
    ),
    "hr": (
        f"{_COMMON} This is an HR screen. Ask about motivation, expectations, "
        "career path, ways of working and team fit. Never ask about a "
        "programming language, tool or technology: a technical round covers "
        "those."
    ),
    "custom": (
        f"{_COMMON} Follow the template's description for what this "
        "interview covers and the style of question it calls for."
    ),
}


def _normalised(text: str) -> str:
    return " ".join(text.lower().split())


def _build_prompt(
    *,
    name: str,
    description: str | None,
    job_title: str | None,
    job_description: str | None,
    existing: list[str],
    count_hint: str = "",
) -> str:
    template = " — ".join(p for p in (_clean(name), _clean(description or "")) if p)
    parts = [f"The template:\n{_fenced(template)}\n"]
    job = " — ".join(p for p in (
        _clean(job_title or ""), _clean(job_description or "", limit=_MAX_ROLE_CHARS),
    ) if p)
    if job:
        parts.append(
            "It is being written for roles like this job; use it to judge what the "
            f"speciality covers, not to ask about this one opening:\n{_fenced(job)}\n"
        )
    kept = [t for t in (e.strip() for e in existing) if t]
    if kept:
        parts.append(
            "The template already asks these — do NOT repeat them or ask the same thing "
            "in other words:\n" + "\n".join(f"- {_clean(t)}" for t in kept) + "\n"
        )
    parts.append("Return JSON with a `questions` array of {text, criterion}.")
    if count_hint:
        parts.append(count_hint)
    return "\n".join(parts)


async def suggest_template_questions(
    *,
    name: str,
    description: str | None,
    kind: TemplateKind,
    job_title: str | None,
    job_description: str | None,
    existing: list[str],
    llm: LLMClient,
) -> list[SuggestedTemplateQuestion]:
    """5–8 questions for the template; one retry when the count is off.

    Still too many after the retry → the first eight. None at all → ValueError.
    Questions repeating one the template already asks are dropped.
    """
    async def ask(count_hint: str = "") -> list[SuggestedTemplateQuestion]:
        prompt = _build_prompt(
            name=name, description=description, job_title=job_title,
            job_description=job_description, existing=existing, count_hint=count_hint,
        )
        raw = await llm.chat_structured(
            messages=[LLMMessage(role="user", content=prompt)],
            schema=SuggestedTemplateQuestions,
            system=_SYSTEM[kind],
            # Reasoning tokens count against this budget.
            max_tokens=2048,
            temperature=0.3,
        )
        return raw.questions

    questions = await ask()
    if not (_MIN_COUNT <= len(questions) <= _MAX_COUNT):
        questions = await ask(
            f"You must return between {_MIN_COUNT} and {_MAX_COUNT} questions."
        )
    if not questions:
        raise ValueError("the model suggested no questions")
    seen = {_normalised(e) for e in existing if e.strip()}
    fresh = [q for q in questions if _normalised(q.text) not in seen]
    return fresh[:_MAX_COUNT]
