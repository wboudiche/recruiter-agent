"""Assembling a kit from a job baseline and generated probes.

Pure functions: no database, no LLM. The two rules that matter most in the
feature live here, so they can be tested without either.
"""
import uuid
from collections.abc import Collection
from datetime import UTC, datetime, timedelta

from recruiter.schemas.interview import BaselineQuestion, InterviewKit, KitQuestion


# How long a run marked `generating` is assumed to still be working. Long
# enough to cover a slow model call, short enough that a run killed
# mid-flight can be retried rather than stranding the kit forever.
GENERATION_STALE_AFTER = timedelta(seconds=90)


def generation_in_flight(kit: dict | None, *, now: datetime) -> bool:
    """Whether a generation is already running for this kit.

    Used to make `generate` idempotent: a double-click, or two open tabs,
    would otherwise buy a second LLM call whose result simply overwrites the
    first. The staleness window is the escape hatch — a process that dies
    mid-generation leaves the kit marked `generating` for good, and without
    a way past that the recruiter could never retry.

    A `generating` kit carrying no timestamp predates this field, so it is
    treated as retryable for the same reason.
    """
    if (kit or {}).get("status") != "generating":
        return False
    started = (kit or {}).get("generating_since")
    if not started:
        return False
    try:
        ts = datetime.fromisoformat(str(started))
    except (TypeError, ValueError):
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return now - ts < GENERATION_STALE_AFTER


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
    answered_ids: Collection[str] = (),
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

    A question counts as answered two ways. `q.answer`/`q.rating` are the
    LEGACY per-question fields, only ever set on kits recorded before
    answers moved onto per-interviewer sheets. `answered_ids` carries the
    current equivalent: the ids any interviewer's sheet has answered or
    rated, which the caller reads off the assignment rows. Without the
    second, this function preserves nothing at all on a modern kit —
    regenerating would mint fresh probe ids and orphan every draft answer
    keyed to the old ones.

    Questions maintain baseline-then-probe ordering within each group:
    answered baselines, unanswered baselines, answered probes, fresh probes.
    """
    answered = set(answered_ids)

    def _is_answered(q: KitQuestion) -> bool:
        return q.answer is not None or q.rating is not None or q.id in answered

    # Separate answered/rated from untouched questions
    answered_baseline = [
        q for q in existing.questions if _is_answered(q) and q.source == "baseline"
    ]
    answered_probe = [
        q for q in existing.questions if _is_answered(q) and q.source == "probe"
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
