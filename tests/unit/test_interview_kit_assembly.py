from datetime import UTC, datetime, timedelta

from recruiter.models import InterviewTemplate
from recruiter.pipeline.interview_kit import (
    build_kit,
    fixed_questions,
    generation_in_flight,
    merge_regenerated,
    probe_mode_of,
    snapshot_of,
    wants_probes,
)
from recruiter.schemas.interview import BaselineQuestion, InterviewKit, KitQuestion
from recruiter.schemas.interview_template import TemplateSnapshot

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


NOW_DT = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def test_generation_in_flight_while_a_recent_run_is_working() -> None:
    """A double-click must not buy a second LLM call."""
    kit = {"status": "generating",
           "generating_since": (NOW_DT - timedelta(seconds=5)).isoformat()}
    assert generation_in_flight(kit, now=NOW_DT)


def test_generation_not_in_flight_once_a_run_has_gone_stale() -> None:
    """The escape hatch. A process killed mid-generation leaves the kit
    marked `generating` forever; without a staleness window the recruiter
    could never retry and the kit would be stuck with no way out."""
    kit = {"status": "generating",
           "generating_since": (NOW_DT - timedelta(minutes=10)).isoformat()}
    assert not generation_in_flight(kit, now=NOW_DT)


def test_generation_not_in_flight_for_a_kit_that_is_not_generating() -> None:
    assert not generation_in_flight({"status": "ready"}, now=NOW_DT)
    assert not generation_in_flight(None, now=NOW_DT)


def test_a_generating_kit_with_no_timestamp_may_be_retried() -> None:
    """Kits marked generating before this field existed carry no timestamp.
    Treating them as in flight would strand them permanently."""
    assert not generation_in_flight({"status": "generating"}, now=NOW_DT)


def _template(
    *, probe_mode: str, include: bool, qids=("b1",),
) -> InterviewTemplate:
    tpl = InterviewTemplate(
        name="RH screen", probe_mode=probe_mode, include_job_questions=include,
        questions=[{"id": q, "text": f"Template {q}"} for q in qids],
    )
    tpl.id = 7
    return tpl


def _job_baseline():
    return [
        BaselineQuestion(id="b1", text="Job b1"),
        BaselineQuestion(id="b2", text="Job b2"),
    ]


def test_no_template_means_exactly_the_job_baseline_and_probes() -> None:
    """The guarantee that makes this phase safe to ship with zero templates."""
    assert [q.id for q in fixed_questions(None, _job_baseline())] == ["b1", "b2"]
    assert wants_probes(None) is True


def test_template_questions_are_namespaced_so_they_cannot_collide() -> None:
    """Sheets key answers by question id. A template question `b1` and the
    job's own `b1` must stay two questions, or their answers merge."""
    snap = snapshot_of(_template(probe_mode="score_gaps", include=True))
    ids = [q.id for q in fixed_questions(snap, _job_baseline())]

    assert ids == ["t7-b1", "b1", "b2"], "template first, then the job's own, all distinct"


def test_job_questions_left_out_when_the_template_says_so() -> None:
    snap = snapshot_of(_template(probe_mode="none", include=False))
    assert [q.text for q in fixed_questions(snap, _job_baseline())] == ["Template b1"]


def test_probe_mode_none_wants_no_probes() -> None:
    assert wants_probes(
        snapshot_of(_template(probe_mode="none", include=False))
    ) is False
    assert wants_probes(
        snapshot_of(_template(probe_mode="score_gaps", include=True))
    ) is True


def test_the_snapshot_survives_a_round_trip_through_the_database_shape() -> None:
    """The snapshot is stored as a dict on the kit row and read back later;
    the round trip must not lose the namespacing or the switches."""
    snap = snapshot_of(_template(probe_mode="none", include=False))
    again = TemplateSnapshot.model_validate(snap.model_dump())
    assert again == snap


def test_probe_mode_of_reads_the_snapshot_and_defaults_to_score_gaps() -> None:
    """A kit with no template generates the way kits always have."""
    assert probe_mode_of(None) == "score_gaps"
    assert probe_mode_of(snapshot_of(_template(probe_mode="score_gaps", include=True))) \
        == "score_gaps"
    assert probe_mode_of(snapshot_of(_template(probe_mode="profile", include=False))) \
        == "profile"
    assert probe_mode_of(snapshot_of(_template(probe_mode="none", include=False))) == "none"


def test_a_profile_template_still_wants_probes() -> None:
    """`none` is the only mode that skips the model — profile probes need
    one just as much as score-gap probes do, which is what tells the
    no-provider path to fail that track rather than dispatch it."""
    assert wants_probes(snapshot_of(_template(probe_mode="profile", include=False))) is True
    assert wants_probes(snapshot_of(_template(probe_mode="none", include=False))) is False
