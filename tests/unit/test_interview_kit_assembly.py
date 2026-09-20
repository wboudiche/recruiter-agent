from recruiter.pipeline.interview_kit import build_kit, merge_regenerated
from recruiter.schemas.interview import BaselineQuestion, InterviewKit, KitQuestion

NOW = "2026-09-10T10:00:00+00:00"


def _baseline() -> list[BaselineQuestion]:
    return [BaselineQuestion(id="b1", text="Why this role?"),
            BaselineQuestion(id="b2", text="Notice period?")]


def test_build_kit_puts_baseline_first_then_probes() -> None:
    kit = build_kit(_baseline(), ["Describe a K8s incident."],
                    criteria_by_probe=["Kubernetes"], now=NOW)
    assert [q.source for q in kit.questions] == ["baseline", "baseline", "probe"]
    assert [q.text for q in kit.questions][:2] == ["Why this role?", "Notice period?"]
    assert kit.questions[2].criterion == "Kubernetes"
    assert kit.status == "ready"
    assert kit.generated_at == NOW


def test_build_kit_gives_every_question_a_unique_id() -> None:
    kit = build_kit(_baseline(), ["p one", "p two"], criteria_by_probe=[None, None], now=NOW)
    ids = [q.id for q in kit.questions]
    assert len(ids) == len(set(ids))


def test_regeneration_keeps_answered_questions_untouched() -> None:
    """Losing typed interview notes to a stray Retry would be unforgivable."""
    existing = InterviewKit(status="ready", questions=[
        KitQuestion(id="b1", text="Why this role?", source="baseline",
                    answer="Wants scale", rating="strong"),
        KitQuestion(id="p-oldprobe1", text="Old probe", source="probe", answer=None),
    ])
    merged = merge_regenerated(existing, _baseline(), ["Fresh probe"],
                               criteria_by_probe=[None], now=NOW)

    answered = [q for q in merged.questions if q.answer is not None]
    assert len(answered) == 1
    assert answered[0].text == "Why this role?"
    assert answered[0].answer == "Wants scale"
    assert answered[0].rating == "strong"
    assert "Old probe" not in [q.text for q in merged.questions]
    assert "Fresh probe" in [q.text for q in merged.questions]

    # Verify no duplicates and correct totals
    texts = [q.text for q in merged.questions]
    ids = [q.id for q in merged.questions]
    assert len(texts) == len(set(texts)), "Question texts should be unique"
    assert len(ids) == len(set(ids)), "Question ids should be unique"
    # 1 answered baseline + 1 fresh baseline (b2) + 1 fresh probe
    assert len(merged.questions) == 3


def test_regeneration_keeps_rating_only_baseline_question() -> None:
    """A rating recorded without a typed answer is normal mid-interview and
    must not be treated as unanswered — it would otherwise be re-snapshotted
    from the baseline and lose the rating."""
    existing = InterviewKit(status="ready", questions=[
        KitQuestion(id="b1", text="Why this role?", source="baseline",
                    answer=None, rating="weak"),
        KitQuestion(id="b2", text="Notice period?", source="baseline", answer=None),
    ])
    merged = merge_regenerated(existing, _baseline(), [], criteria_by_probe=[], now=NOW)

    kept = next(q for q in merged.questions if q.id == "b1")
    assert kept.rating == "weak"
    assert kept.text == "Why this role?"
    assert kept.answer is None
    # b2 had no answer and no rating, so it's re-snapshotted (not lost).
    assert any(q.id == "b2" for q in merged.questions)


def test_regeneration_keeps_rating_only_probe_question() -> None:
    """Same guarantee for probes: a rating alone must survive, not just an
    answer, and the question must not be silently deleted."""
    existing = InterviewKit(status="ready", questions=[
        KitQuestion(id="p-old1", text="Old probe", source="probe",
                    answer=None, rating="adequate"),
    ])
    merged = merge_regenerated(existing, _baseline(), ["Fresh probe"],
                               criteria_by_probe=[None], now=NOW)

    kept = next(q for q in merged.questions if q.id == "p-old1")
    assert kept.rating == "adequate"
    assert kept.text == "Old probe"
    assert kept.answer is None
    assert "Fresh probe" in [q.text for q in merged.questions]


def test_regeneration_re_snapshots_unanswered_baseline_questions() -> None:
    """Explicit regeneration should pick up the role's current questions."""
    existing = InterviewKit(status="ready", questions=[
        KitQuestion(id="b1", text="Stale baseline wording", source="baseline", answer=None),
    ])
    merged = merge_regenerated(existing, _baseline(), [], criteria_by_probe=[], now=NOW)
    texts = [q.text for q in merged.questions]
    assert "Stale baseline wording" not in texts
    assert "Why this role?" in texts


def test_regeneration_maintains_baseline_then_probe_ordering() -> None:
    """Questions must stay in baseline-then-probe order to avoid reordering during
    live interviews. This tests the critical case: answered probe and unanswered
    baseline should not reorder.
    """
    existing = InterviewKit(status="ready", questions=[
        KitQuestion(id="b1", text="Why this role?", source="baseline", answer=None),
        KitQuestion(id="p-answered1", text="Answered probe", source="probe",
                    answer="Strong answer", rating="strong"),
    ])
    merged = merge_regenerated(existing, _baseline(), ["Fresh probe"],
                               criteria_by_probe=[None], now=NOW)

    # Extract sources and texts in order
    sources = [q.source for q in merged.questions]
    texts = [q.text for q in merged.questions]

    # All baseline questions must come before all probe questions
    baseline_indices = [i for i, s in enumerate(sources) if s == "baseline"]
    probe_indices = [i for i, s in enumerate(sources) if s == "probe"]
    if baseline_indices and probe_indices:
        assert max(baseline_indices) < min(probe_indices), (
            "Baseline questions must come before probe questions"
        )

    # Verify no duplicates
    assert len(texts) == len(set(texts)), "Question texts should be unique"
    assert len([q.id for q in merged.questions]) == len(
        set([q.id for q in merged.questions])
    ), "Question ids should be unique"

    # Verify answered probe is present and fresh probe is there
    assert "Answered probe" in texts
    assert "Fresh probe" in texts


def test_regeneration_keeps_a_probe_answered_only_in_a_sheet() -> None:
    """Answers live on interviewer sheets now, not on the question. A probe
    someone has already answered must survive regeneration WITH ITS ID — a
    fresh id orphans their answer, which is keyed by question id."""
    existing = InterviewKit(status="ready", questions=[
        KitQuestion(id="p-old1", text="Old probe", source="probe"),
    ])

    merged = merge_regenerated(
        existing, _baseline(), ["Fresh probe"],
        criteria_by_probe=[None], now=NOW, answered_ids={"p-old1"},
    )

    kept = next(q for q in merged.questions if q.id == "p-old1")
    assert kept.text == "Old probe"
    assert "Fresh probe" in [q.text for q in merged.questions]


def test_regeneration_keeps_a_baseline_answered_only_in_a_sheet() -> None:
    """Same guarantee for baselines: answered ones keep their recorded
    wording rather than being re-snapshotted from the job underneath a
    recorded answer."""
    existing = InterviewKit(status="ready", questions=[
        KitQuestion(id="b1", text="Wording as asked", source="baseline"),
    ])

    merged = merge_regenerated(
        existing, _baseline(), [],
        criteria_by_probe=[], now=NOW, answered_ids={"b1"},
    )

    kept = next(q for q in merged.questions if q.id == "b1")
    assert kept.text == "Wording as asked"
    # b2 was never asked, so it still arrives from the job's current baseline.
    assert any(q.id == "b2" for q in merged.questions)
