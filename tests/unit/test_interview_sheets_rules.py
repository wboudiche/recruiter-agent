from datetime import UTC, datetime

from recruiter.models import InterviewAssignment, Role, User
from recruiter.pipeline.interview_sheets import (
    all_submitted,
    can_edit_questions,
    is_frozen,
    prune_answers,
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
    rows = [_row(1, True), _row(2, False)]
    assert visible_sheets(rows, user=_user(1, Role.VIEWER)) == rows


def test_unassigned_viewer_sees_no_sheets() -> None:
    rows = [_row(1, True), _row(2, True)]
    assert visible_sheets(rows, user=_user(3, Role.VIEWER)) == []


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
