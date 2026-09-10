import pytest
from pydantic import ValidationError

from recruiter.schemas.interview import BaselineQuestion, InterviewKit, KitQuestion


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
