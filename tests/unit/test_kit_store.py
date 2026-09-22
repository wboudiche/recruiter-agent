from recruiter.models.interview_kit_row import InterviewKitRow
from recruiter.pipeline.kit_store import DEFAULT_TRACK, apply_content, content_of, track_key
from recruiter.schemas.interview import InterviewKit, KitQuestion


def _row() -> InterviewKitRow:
    return InterviewKitRow(
        application_id=1, round=1, track="default", status="ready",
        error=None, generated_at="2026-09-20T10:00:00+00:00",
        generating_since=None, submitted_at=None, closed_at=None,
        questions=[{"id": "q1", "text": "Why?", "source": "probe"}],
    )


def test_content_of_reads_the_row_as_the_api_shape() -> None:
    kit = content_of(_row())
    assert kit.status == "ready"
    assert kit.generated_at == "2026-09-20T10:00:00+00:00"
    assert [q.id for q in kit.questions] == ["q1"]


def test_apply_content_writes_every_field_back() -> None:
    """A round trip must not silently drop a field — the row and the schema
    have to stay in step as either gains one."""
    row = _row()
    apply_content(row, InterviewKit(
        status="error", error="model unavailable",
        generated_at="2026-09-21T09:00:00+00:00",
        generating_since="2026-09-21T08:59:00+00:00",
        submitted_at="2026-09-21T07:00:00+00:00",
        closed_at="2026-09-21T10:00:00+00:00",
        questions=[KitQuestion(id="q2", text="How?", source="baseline")],
    ))
    assert row.status == "error"
    assert row.error == "model unavailable"
    assert row.generated_at == "2026-09-21T09:00:00+00:00"
    assert row.generating_since == "2026-09-21T08:59:00+00:00"
    assert row.submitted_at == "2026-09-21T07:00:00+00:00"
    assert row.closed_at == "2026-09-21T10:00:00+00:00"
    assert [q["id"] for q in row.questions] == ["q2"]


def test_round_trip_is_lossless() -> None:
    row = _row()
    apply_content(row, content_of(row))
    assert content_of(row).model_dump() == content_of(_row()).model_dump()


def test_a_track_key_is_derived_from_its_template() -> None:
    assert track_key(None) == DEFAULT_TRACK == "default"
    assert track_key(7) == "t7"
