import pytest

from recruiter.llm.client import FakeLLMClient
from recruiter.pipeline.interview_kit_generator import generate_probes
from recruiter.schemas.interview import BaselineQuestion, GeneratedQuestion, GeneratedQuestions
from recruiter.schemas.job import CriteriaItem


@pytest.mark.asyncio
async def test_prompt_carries_the_score_rationales() -> None:
    """The rationales are the point: they already name the doubt to probe."""
    llm = FakeLLMClient(structured_responses=[
        GeneratedQuestions(questions=[GeneratedQuestion(text="Probe?", criterion="Kubernetes")]),
    ])
    await generate_probes(
        profile="Ingénieur DevOps, 2 ans",
        criteria=[CriteriaItem(name="Kubernetes", weight=0.2, description="prod clusters")],
        score_breakdown=[{"criterion": "Kubernetes", "score": 60,
                          "rationale": "no evidence of production-grade clusters"}],
        baseline=[BaselineQuestion(id="b1", text="Why this role?")],
        llm=llm,
    )
    prompt = llm.calls[0]["messages"][0].content
    assert "no evidence of production-grade clusters" in prompt
    assert "Why this role?" in prompt, "baseline must be shown so probes don't duplicate it"


@pytest.mark.asyncio
async def test_uses_a_budget_large_enough_for_a_reasoning_model() -> None:
    """512 is what made query suggestion fail with null content (PR #17)."""
    llm = FakeLLMClient(structured_responses=[GeneratedQuestions(questions=[])])
    await generate_probes(profile="p", criteria=[], score_breakdown=None, baseline=[], llm=llm)
    assert llm.calls[0]["max_tokens"] >= 2048


@pytest.mark.asyncio
async def test_returns_the_generated_questions() -> None:
    llm = FakeLLMClient(structured_responses=[
        GeneratedQuestions(questions=[GeneratedQuestion(text="A?", criterion=None)]),
    ])
    out = await generate_probes(profile="p", criteria=[], score_breakdown=None,
                                baseline=[], llm=llm)
    assert [q.text for q in out.questions] == ["A?"]


# --- drafting a single extra question ------------------------------------
# "Add question" already covers writing one yourself. This is the AI path:
# one question at a time, optionally steered by a hint, and never repeating
# something the kit already asks.


@pytest.mark.asyncio
async def test_draft_question_passes_the_hint_and_the_existing_questions() -> None:
    from recruiter.pipeline.interview_kit_generator import draft_question

    llm = FakeLLMClient(structured_responses=[
        GeneratedQuestions(questions=[
            GeneratedQuestion(text="How do you handle Terraform state locking?",
                              criterion="Infrastructure as code"),
        ]),
    ])
    await draft_question(
        profile="DevOps engineer",
        criteria=[],
        score_breakdown=None,
        existing_questions=["Describe a production Kubernetes outage you owned."],
        hint="Terraform state locking",
        llm=llm,
    )
    prompt = llm.calls[0]["messages"][0].content
    assert "Terraform state locking" in prompt
    assert "Describe a production Kubernetes outage you owned." in prompt, (
        "questions already in the kit must be shown so the draft does not repeat one"
    )
    assert llm.calls[0]["max_tokens"] >= 2048


@pytest.mark.asyncio
async def test_draft_question_without_a_hint_still_works() -> None:
    """Empty hint means 'suggest anything missing', not an error."""
    from recruiter.pipeline.interview_kit_generator import draft_question

    llm = FakeLLMClient(structured_responses=[
        GeneratedQuestions(questions=[
            GeneratedQuestion(text="Walk me through your last incident.", criterion=None),
        ]),
    ])
    out = await draft_question(
        profile="p", criteria=[], score_breakdown=None,
        existing_questions=[], hint=None, llm=llm,
    )
    assert out.text == "Walk me through your last incident."


@pytest.mark.asyncio
async def test_draft_question_caps_an_overlong_hint() -> None:
    """A long paste must not swamp the candidate context in the prompt."""
    from recruiter.pipeline.interview_kit_generator import draft_question

    llm = FakeLLMClient(structured_responses=[
        GeneratedQuestions(questions=[GeneratedQuestion(text="Q?", criterion=None)]),
    ])
    await draft_question(
        profile="p", criteria=[], score_breakdown=None,
        existing_questions=[], hint="x" * 5000, llm=llm,
    )
    prompt = llm.calls[0]["messages"][0].content
    assert "x" * 5000 not in prompt
    assert len(prompt) < 3000


# --- profile probes ------------------------------------------------------
# An RH conversation asks about the path, not the stack: these questions are
# built from the candidate's own history and what enrichment found, and the
# technical scoring is deliberately kept out of the prompt.


@pytest.mark.asyncio
async def test_profile_probes_are_built_from_the_history_and_enrichment() -> None:
    from recruiter.pipeline.interview_kit_generator import generate_profile_probes

    llm = FakeLLMClient(structured_responses=[
        GeneratedQuestions(questions=[
            GeneratedQuestion(text="What made you leave Acme after eight months?",
                              criterion="moves"),
        ]),
    ])

    await generate_profile_probes(
        profile=(
            "Marie Dupont · Staff SRE · Lyon\n"
            "- Staff SRE at Acme (2024 – 2025): owned the cluster migration.\n"
            "Found elsewhere online:\n"
            "- github: maintains a Terraform provider with 400 stars."
        ),
        baseline=[BaselineQuestion(id="b1", text="Why this company?")],
        llm=llm,
    )

    prompt = llm.calls[0]["messages"][0].content
    assert "owned the cluster migration" in prompt, "the history is what it asks about"
    assert "Terraform provider with 400 stars" in prompt, "enrichment steers a question too"
    assert "Why this company?" in prompt, "the curated questions must not be duplicated"


@pytest.mark.asyncio
async def test_profile_probes_never_see_the_technical_scoring() -> None:
    """The whole point of the mode: an RH round must not inherit questions
    built from the score breakdown."""
    from recruiter.pipeline.interview_kit_generator import generate_profile_probes

    llm = FakeLLMClient(structured_responses=[GeneratedQuestions(questions=[])])

    await generate_profile_probes(profile="Marie Dupont", baseline=[], llm=llm)

    call = llm.calls[0]
    text = call["messages"][0].content + (call.get("system") or "")
    for forbidden in ("scored", "rationale", "criteria", "weight"):
        assert forbidden not in text.lower(), f"{forbidden!r} leaked into the profile prompt"


@pytest.mark.asyncio
async def test_profile_probes_may_return_nothing_for_a_thin_profile() -> None:
    """Told to ask only what the history supports, the model is allowed to
    return nothing rather than invent filler — the kit then holds just its
    curated questions."""
    from recruiter.pipeline.interview_kit_generator import generate_profile_probes

    llm = FakeLLMClient(structured_responses=[GeneratedQuestions(questions=[])])

    out = await generate_profile_probes(profile="Marie Dupont", baseline=[], llm=llm)

    assert out.questions == []
    assert llm.calls[0]["max_tokens"] >= 2048
