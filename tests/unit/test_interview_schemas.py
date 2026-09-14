import pytest
from pydantic import ValidationError

from recruiter.schemas.interview import (
    BaselineQuestion,
    InterviewKit,
    InterviewSheet,
    KitQuestion,
)


def test_kit_question_round_trips_through_json() -> None:
    q = KitQuestion(id="q1", text="Describe a production incident.", source="probe",
                    criterion="Kubernetes", answer=None, rating=None)
    assert KitQuestion.model_validate(q.model_dump()) == q


def test_rating_rejects_values_outside_the_three_allowed() -> None:
    with pytest.raises(ValidationError):
        KitQuestion(id="q1", text="t", source="probe", rating="excellent")


def test_status_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError):
        InterviewKit(status="finished", questions=[])


def test_empty_question_text_is_rejected() -> None:
    """A blank question is not a question; it would render as an empty row."""
    with pytest.raises(ValidationError):
        BaselineQuestion(id="b1", text="   ")


def test_sheet_defaults_are_empty() -> None:
    sheet = InterviewSheet()
    assert sheet.answers == {}
    assert sheet.verdict.decision is None
    assert sheet.verdict.note is None


def test_sheet_accepts_answers_keyed_by_question_id() -> None:
    sheet = InterviewSheet.model_validate({
        "answers": {"q1": {"answer": "Ran it for two years.", "rating": "strong"}},
        "verdict": {"decision": "hire", "note": "Solid."},
    })
    assert sheet.answers["q1"].rating == "strong"
    assert sheet.verdict.decision == "hire"


def test_sheet_rejects_unknown_rating_and_decision() -> None:
    with pytest.raises(ValidationError):
        InterviewSheet.model_validate({"answers": {"q1": {"answer": None, "rating": "great"}}})
    with pytest.raises(ValidationError):
        InterviewSheet.model_validate({"verdict": {"decision": "maybe", "note": None}})


def test_kit_question_added_by_and_kit_closed_at_default_to_none() -> None:
    q = KitQuestion(id="q1", text="Why?", source="probe")
    assert q.added_by is None
    kit = InterviewKit(status="ready")
    assert kit.closed_at is None
