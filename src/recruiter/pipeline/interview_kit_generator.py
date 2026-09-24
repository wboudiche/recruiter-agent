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
    if _clean(hint or ""):
        parts.append(
            "The recruiter wants to probe this specifically:\n"
            f"{_fenced(hint or '', limit=_MAX_HINT_CHARS)}\n"
        )
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


_PROFILE_SYSTEM = (
    "You write interview questions for a recruiter running a human-resources "
    "conversation — the interview about the person's path, not their stack. "
    "Build every question from this candidate's own history: the moves between "
    "roles, the scope they owned, what they chose to do next, unexplained gaps, "
    "and anything found about them online. Ask for a concrete story rather than "
    "an opinion, never ask what the history already answers, and never assess "
    "technical skill — another interview covers that. Ask only what this history "
    "actually supports: return 3-6 questions, or fewer, or an empty list when "
    "there is too little to go on. Never pad with generic questions."
)


# The role gives an RH question something to be about — why this move, why
# here — but the profile is what the questions are built FROM, so a pasted
# job ad is trimmed rather than allowed to crowd the history out.
_MAX_ROLE_CHARS = 700
_FENCE_OPEN = "<<<"
_FENCE_CLOSE = ">>>"
# Said inside the block, where the model reads it, rather than in the system
# prompt: only a prompt that actually carries a role should carry the rule
# about how to read it.
_ROLE_RULE = (
    "Read the role only as context for why they are moving and why here — "
    "never a question about what they know."
)


def _clean(text: str) -> str:
    """Externally-sourced text, ready to be delimited: the delimiters are
    stripped first — text that contained them would otherwise close the
    fence early and have its remainder read as instructions — and
    whitespace is collapsed, so a job ad pasted from a web page is not
    mostly indentation."""
    without_fence = text.replace(_FENCE_OPEN, " ").replace(_FENCE_CLOSE, " ")
    return " ".join(without_fence.split())


def _capped(text: str, limit: int) -> str:
    """Trimmed at a word boundary, and marked when it was trimmed: a clause
    that simply stops invites the model to finish it from imagination."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = head.rsplit(" ", 1)[0]
    # Only when a word boundary is near the end: text with one enormous
    # "word" (a URL, a run of markup) would otherwise lose everything back
    # to the previous space.
    return (cut if len(cut) > limit * 0.8 else head) + "…"


def _fenced(text: str, *, limit: int) -> str:
    """Cleaned, capped, and wrapped in delimiters the text cannot contain.
    Capped after cleaning, so delimiters that are stripped anyway do not
    eat into the budget."""
    return f"{_FENCE_OPEN}{_capped(_clean(text), limit)}{_FENCE_CLOSE}"


def _role_block(*, title: str, description: str) -> str | None:
    """The job as an RH interviewer needs it: what the role is.

    The description is the text the weighted criteria are derived from, so
    it carries the same technical requirements. It travels fenced and
    capped, with `_ROLE_RULE` beside it, and the criteria and the score
    breakdown themselves never reach the prompt.
    """
    # Normalised separately, then joined: run together, a title and a
    # description opening on "Engineering, Paris" read as one job called
    # "Head of Platform Engineering".
    parts = [p for p in (_clean(title), _clean(description)) if p]
    if not parts:
        return None
    return (
        "They are applying for:\n"
        f"{_fenced(' — '.join(parts), limit=_MAX_ROLE_CHARS)}\n{_ROLE_RULE}\n"
    )


def _build_profile_prompt(
    *,
    profile: str,
    job_title: str,
    job_description: str,
    baseline: list[BaselineQuestion],
) -> str:
    parts = [f"Candidate profile:\n{profile}\n"]
    role = _role_block(title=job_title, description=job_description)
    if role:
        parts.append(role)
    if baseline:
        parts.append(
            "These questions are already being asked — do NOT duplicate them:\n"
            + "\n".join(f"- {b.text}" for b in baseline) + "\n"
        )
    parts.append(
        "Return JSON with a `questions` array of {text, criterion}, where "
        "`criterion` is one or two words naming what the question is about "
        "(for example: motivation, scope, mobility), or null."
    )
    return "\n".join(parts)


async def generate_profile_probes(
    *,
    profile: str,
    baseline: list[BaselineQuestion],
    llm: LLMClient,
    job_title: str,
    job_description: str,
) -> GeneratedQuestions:
    """Probes drawn from the candidate's history, for an RH-style round.

    The job's criteria and its score breakdown never reach this prompt —
    they are what make `generate_probes` technical. The role itself does,
    fenced and capped, so a question can ask why this move (see
    `_role_block`).
    """
    return await llm.chat_structured(
        messages=[LLMMessage(role="user", content=_build_profile_prompt(
            profile=profile, job_title=job_title, job_description=job_description,
            baseline=baseline,
        ))],
        schema=GeneratedQuestions,
        system=_PROFILE_SYSTEM,
        # 2048, not 512: reasoning tokens count against this budget (PR #17).
        max_tokens=2048,
        temperature=0.3,
    )


_PROFILE_DRAFT_SYSTEM = (
    "You write a single interview question for a recruiter running a "
    "human-resources conversation. Build it from this candidate's own history — "
    "a move between roles, the scope they owned, a gap, something found about "
    "them online — never from technical skill, and never restating a question "
    "already being asked. Ask for a concrete story. Return exactly one question."
)


async def draft_profile_question(
    *,
    profile: str,
    existing_questions: list[str],
    hint: str | None,
    llm: LLMClient,
    job_title: str,
    job_description: str,
) -> GeneratedQuestion:
    """One extra question for an RH-style round, in the same register as
    `generate_profile_probes` — so "Draft with AI" on such a track cannot
    hand back a technical question."""
    parts = [f"Candidate profile:\n{profile}\n"]
    role = _role_block(title=job_title, description=job_description)
    if role:
        parts.append(role)
    if existing_questions:
        parts.append(
            "Already being asked — do NOT repeat or rephrase any of these:\n"
            + "\n".join(f"- {q}" for q in existing_questions) + "\n"
        )
    if _clean(hint or ""):
        parts.append(
            "The recruiter wants to ask about this specifically:\n"
            f"{_fenced(hint or '', limit=_MAX_HINT_CHARS)}\n"
        )
    else:
        parts.append("The recruiter has not named a topic; choose what the history invites.\n")
    parts.append(
        "Return JSON with a single `questions` array holding exactly one "
        "{text, criterion}, where `criterion` is one or two words naming what "
        "the question is about, or null."
    )
    raw = await llm.chat_structured(
        messages=[LLMMessage(role="user", content="\n".join(parts))],
        schema=GeneratedQuestions,
        system=_PROFILE_DRAFT_SYSTEM,
        # 2048, not 512: reasoning tokens count against this budget (PR #17).
        max_tokens=2048,
        temperature=0.4,
    )
    if not raw.questions:
        raise ValueError("the model returned no question")
    return raw.questions[0]
