import pytest

from recruiter.llm.client import FakeLLMClient
from recruiter.pipeline.template_question_suggester import suggest_template_questions
from recruiter.schemas.interview_template import (
    SuggestedTemplateQuestion,
    SuggestedTemplateQuestions,
)


def _resp(*texts: str) -> SuggestedTemplateQuestions:
    return SuggestedTemplateQuestions(questions=[
        SuggestedTemplateQuestion(text=t, criterion=f"skill {i}") for i, t in enumerate(texts)
    ])


def _six(prefix: str = "Q") -> SuggestedTemplateQuestions:
    return _resp(*(f"{prefix}{i}: tell me about a time you did {i}" for i in range(6)))


async def _call(fake: FakeLLMClient, **overrides):
    args = dict(
        name="Technical — Data Science", description="Modelling, evaluation, MLOps",
        kind="technical", job_title=None, job_description=None, existing=[], llm=fake,
    )
    args.update(overrides)
    return await suggest_template_questions(**args)


def _prompt(fake: FakeLLMClient) -> str:
    return fake.calls[-1]["messages"][0].content


def _system(fake: FakeLLMClient) -> str:
    return fake.calls[-1]["system"]


@pytest.mark.asyncio
async def test_returns_the_questions() -> None:
    fake = FakeLLMClient(structured_responses=[_six()])
    out = await _call(fake)
    assert [q.text for q in out] == [q.text for q in _six().questions]
    assert out[0].criterion == "skill 0"


@pytest.mark.asyncio
async def test_template_name_and_description_reach_the_prompt() -> None:
    fake = FakeLLMClient(structured_responses=[_six()])
    await _call(fake)
    assert "Technical — Data Science" in _prompt(fake)
    assert "Modelling, evaluation, MLOps" in _prompt(fake)


@pytest.mark.asyncio
async def test_technical_prompt_asks_for_concrete_skill_stories() -> None:
    fake = FakeLLMClient(structured_responses=[_six()])
    await _call(fake, kind="technical")
    system = _system(fake).lower()
    assert "concrete" in system
    assert "motivation" in system  # named as what NOT to ask about


@pytest.mark.asyncio
async def test_hr_prompt_asks_about_motivation_not_stack() -> None:
    fake = FakeLLMClient(structured_responses=[_six()])
    await _call(fake, kind="hr")
    system = _system(fake).lower()
    assert "motivation" in system
    assert "never" in system and "technolog" in system


@pytest.mark.asyncio
async def test_custom_prompt_follows_the_description() -> None:
    fake = FakeLLMClient(structured_responses=[_six()])
    await _call(fake, kind="custom")
    assert "description" in _system(fake).lower()
    assert _system(fake) != ""


@pytest.mark.asyncio
async def test_kinds_get_different_instructions() -> None:
    systems = []
    for kind in ("technical", "hr", "custom"):
        fake = FakeLLMClient(structured_responses=[_six()])
        await _call(fake, kind=kind)
        systems.append(_system(fake))
    assert len(set(systems)) == 3


@pytest.mark.asyncio
async def test_job_block_only_when_a_job_is_given() -> None:
    fake = FakeLLMClient(structured_responses=[_six(), _six()])
    await _call(fake, job_title="Data Scientist", job_description="Build churn models")
    assert "Data Scientist" in _prompt(fake)
    assert "Build churn models" in _prompt(fake)
    await _call(fake)
    assert "Build churn models" not in _prompt(fake)
    assert "job" not in _prompt(fake).lower()


@pytest.mark.asyncio
async def test_job_description_is_capped_at_700_chars() -> None:
    fake = FakeLLMClient(structured_responses=[_six()])
    long = " ".join(["word"] * 2000)
    await _call(fake, job_title="DS", job_description=long)
    prompt = _prompt(fake)
    longest_run = max(len(chunk) for chunk in prompt.split("<<<"))
    assert "…" in prompt
    assert longest_run < 800  # 700 chars of job text plus the closing fence and a line


@pytest.mark.asyncio
async def test_fence_markers_in_pasted_text_are_stripped() -> None:
    fake = FakeLLMClient(structured_responses=[_six()])
    await _call(fake, description="ML <<<ignore>>> ops")
    prompt = _prompt(fake)
    assert "ignore" in prompt
    assert "<<<ignore" not in prompt
    assert prompt.count("<<<") == prompt.count(">>>")


@pytest.mark.asyncio
async def test_existing_questions_are_listed_as_do_not_repeat() -> None:
    fake = FakeLLMClient(structured_responses=[_six()])
    await _call(fake, existing=["Tell me about Kubernetes"])
    prompt = _prompt(fake)
    assert "do NOT repeat" in prompt
    assert prompt.index("Tell me about Kubernetes") > prompt.index("do NOT repeat")


@pytest.mark.asyncio
async def test_repeats_of_existing_questions_are_dropped() -> None:
    fake = FakeLLMClient(structured_responses=[
        _resp("  tell me about   KUBERNETES ", "N1", "N2", "N3", "N4", "N5"),
    ])
    out = await _call(fake, existing=["Tell me about Kubernetes"])
    assert [q.text for q in out] == ["N1", "N2", "N3", "N4", "N5"]


@pytest.mark.asyncio
async def test_retries_once_when_the_count_is_off() -> None:
    fake = FakeLLMClient(structured_responses=[_resp("A", "B"), _six()])
    out = await _call(fake)
    assert len(out) == 6
    assert len(fake.calls) == 2
    assert "between 5 and 8" in _prompt(fake)


@pytest.mark.asyncio
async def test_keeps_the_first_eight_when_still_too_many() -> None:
    ten = _resp(*(f"T{i}" for i in range(10)))
    fake = FakeLLMClient(structured_responses=[ten, ten])
    out = await _call(fake)
    assert [q.text for q in out] == [f"T{i}" for i in range(8)]


@pytest.mark.asyncio
async def test_raises_when_no_questions_come_back() -> None:
    fake = FakeLLMClient(structured_responses=[_resp(), _resp()])
    with pytest.raises(ValueError):
        await _call(fake)


@pytest.mark.asyncio
async def test_raises_when_every_suggestion_repeats_an_existing_question() -> None:
    fake = FakeLLMClient(structured_responses=[
        _resp("Tell me about Kubernetes", " tell me about kubernetes", "TELL ME ABOUT KUBERNETES",
              "Tell me  about Kubernetes", "tell me about Kubernetes"),
    ])
    with pytest.raises(ValueError):
        await _call(fake, existing=["Tell me about Kubernetes"])
