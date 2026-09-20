from datetime import UTC, datetime

from recruiter.models import InterviewAssignment, Role, User
from recruiter.pipeline.interview_sheets import (
    all_submitted,
    answered_question_ids,
    can_edit_questions,
    is_frozen,
    prune_answers,
    sheet_has_content,
    visible_sheets,
)
from recruiter.schemas.interview import InterviewSheet


def _user(uid: int, role: Role) -> User:
    u = User(email=f"u{uid}@acme.com", role=role, is_active=True)
    u.id = uid
    return u


def _row(uid: int, submitted: bool) -> InterviewAssignment:
    return InterviewAssignment(
        application_id=1, user_id=uid, sheet={},
        submitted_at=datetime.now(UTC) if submitted else None,
    )


def test_frozen_once_any_sheet_is_submitted() -> None:
    assert not is_frozen([])
    assert not is_frozen([_row(1, False), _row(2, False)])
    assert is_frozen([_row(1, False), _row(2, True)])


def test_all_submitted_requires_every_row_and_at_least_one() -> None:
    assert not all_submitted([])
    assert not all_submitted([_row(1, True), _row(2, False)])
    assert all_submitted([_row(1, True), _row(2, True)])


def test_recruiter_and_admin_see_every_sheet() -> None:
    rows = [_row(1, False), _row(2, True)]
    assert visible_sheets(rows, user=_user(9, Role.RECRUITER)) == rows
    assert visible_sheets(rows, user=_user(9, Role.ADMIN)) == rows


def test_assigned_interviewer_sees_only_own_sheet_until_submitted() -> None:
    rows = [_row(1, False), _row(2, True)]
    assert visible_sheets(rows, user=_user(1, Role.VIEWER)) == [rows[0]]


def test_assigned_interviewer_sees_all_after_own_submit() -> None:
    """After submitting, drafts stay private to their author: row 2 (not
    submitted) stays hidden even though the caller has now submitted."""
    rows = [_row(1, True), _row(2, False), _row(3, True)]
    assert visible_sheets(rows, user=_user(1, Role.VIEWER)) == [rows[0], rows[2]]


def test_unassigned_viewer_sees_no_sheets() -> None:
    rows = [_row(1, True), _row(2, True)]
    assert visible_sheets(rows, user=_user(3, Role.VIEWER)) == []


def test_answered_question_ids_unions_every_sheet() -> None:
    """Feeds merge_regenerated: a question any interviewer has answered or
    rated must keep its id through a regeneration."""
    rows = [_row(1, False), _row(2, False)]
    rows[0].sheet = {"answers": {"q1": {"answer": "yes", "rating": None}}}
    rows[1].sheet = {"answers": {"q2": {"answer": None, "rating": "weak"}}}

    assert answered_question_ids(rows) == {"q1", "q2"}


def test_answered_question_ids_ignores_empty_and_untouched_answers() -> None:
    """The client posts a row per rendered question, so blank answers are the
    normal case — counting them would pin every question forever."""
    rows = [_row(1, False)]
    rows[0].sheet = {"answers": {
        "blank": {"answer": "", "rating": None},
        "untouched": {"answer": None, "rating": None},
        "real": {"answer": "something", "rating": None},
    }}

    assert answered_question_ids(rows) == {"real"}


def test_prune_drops_answers_for_questions_no_longer_in_kit() -> None:
    sheet = InterviewSheet.model_validate({
        "answers": {
            "keep": {"answer": "a", "rating": None},
            "gone": {"answer": "b", "rating": None},
        },
    })
    pruned = prune_answers(sheet, {"keep"})
    assert set(pruned.answers) == {"keep"}


def test_only_recruiters_and_admins_edit_questions() -> None:
    assert can_edit_questions(_user(1, Role.ADMIN))
    assert can_edit_questions(_user(1, Role.RECRUITER))
    assert not can_edit_questions(_user(1, Role.VIEWER))


def test_sheet_has_content_false_when_empty() -> None:
    assert not sheet_has_content({})
    assert not sheet_has_content({"answers": {}, "verdict": {"decision": None, "note": None}})


def test_sheet_has_content_true_for_an_answer() -> None:
    assert sheet_has_content({
        "answers": {"q1": {"answer": "Handled it calmly.", "rating": None}},
        "verdict": {"decision": None, "note": None},
    })


def test_sheet_has_content_true_for_a_rating_with_no_text() -> None:
    assert sheet_has_content({
        "answers": {"q1": {"answer": None, "rating": "strong"}},
        "verdict": {"decision": None, "note": None},
    })


def test_sheet_has_content_true_for_a_verdict_note() -> None:
    assert sheet_has_content({
        "answers": {},
        "verdict": {"decision": None, "note": "Strong communicator."},
    })


def test_sheet_has_content_true_for_a_verdict_decision() -> None:
    assert sheet_has_content({
        "answers": {},
        "verdict": {"decision": "hire", "note": None},
    })
