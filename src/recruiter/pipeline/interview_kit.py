"""Assembling a kit from a job baseline and generated probes.

Pure functions: no database, no LLM. The two rules that matter most in the
feature live here, so they can be tested without either.
"""
import uuid

from recruiter.schemas.interview import BaselineQuestion, InterviewKit, KitQuestion


def _probe_questions(probes: list[str], criteria_by_probe: list[str | None]) -> list[KitQuestion]:
    return [
        KitQuestion(
            id=f"p-{uuid.uuid4().hex[:8]}",
            text=text,
            source="probe",
            criterion=criteria_by_probe[i] if i < len(criteria_by_probe) else None,
        )
        for i, text in enumerate(probes)
    ]


def _baseline_questions(baseline: list[BaselineQuestion]) -> list[KitQuestion]:
    return [
        KitQuestion(id=b.id, text=b.text, source="baseline", criterion=b.criterion)
        for b in baseline
    ]


def build_kit(
    baseline: list[BaselineQuestion],
    probes: list[str],
    *,
    criteria_by_probe: list[str | None],
    now: str,
) -> InterviewKit:
    """Snapshot the baseline, then append the generated probes."""
    return InterviewKit(
        status="ready",
        generated_at=now,
        questions=_baseline_questions(baseline) + _probe_questions(probes, criteria_by_probe),
    )


def merge_regenerated(
    existing: InterviewKit,
    baseline: list[BaselineQuestion],
    probes: list[str],
    *,
    criteria_by_probe: list[str | None],
    now: str,
) -> InterviewKit:
    """Regenerate, keeping every question that already has an answer or a
    rating.

    Answered or rated questions are evidence of what was actually asked and
    said (or judged) during an interview — a recruiter routinely rates a
    question they didn't transcribe an answer for — so both survive
    regeneration verbatim, including their rating and their original
    wording. Only questions with neither an answer nor a rating are
    replaced: baseline ones re-snapshot from the job's current baseline,
    probes are regenerated.

    Questions maintain baseline-then-probe ordering within each group:
    answered baselines, unanswered baselines, answered probes, fresh probes.
    """
    # Separate answered/rated from untouched questions
    answered_baseline = [
        q for q in existing.questions
        if (q.answer is not None or q.rating is not None) and q.source == "baseline"
    ]
    answered_probe = [
        q for q in existing.questions
        if (q.answer is not None or q.rating is not None) and q.source == "probe"
    ]
    answered_baseline_ids = {q.id for q in answered_baseline}

    # Generate fresh unanswered questions
    fresh_baseline = [
        q for q in _baseline_questions(baseline) if q.id not in answered_baseline_ids
    ]
    fresh_probes = _probe_questions(probes, criteria_by_probe)

    # Combine in baseline-then-probe order within each group
    return InterviewKit(
        status="ready",
        generated_at=now,
        submitted_at=existing.submitted_at,
        questions=(
            answered_baseline + fresh_baseline + answered_probe + fresh_probes
        ),
    )
