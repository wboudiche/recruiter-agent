from datetime import UTC, datetime

from recruiter.models import InterviewAssignment, InterviewKitRow, Role, User
from recruiter.pipeline.interview_sheets import (
    all_submitted,
    answered_question_ids,
    rows_in_round,
    round_complete,
    rows_in_track,
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


def _row(uid: int, submitted: bool, round_number: int = 1) -> InterviewAssignment:
    return InterviewAssignment(
        application_id=1, user_id=uid, sheet={}, round=round_number,
        submitted_at=datetime.now(UTC) if submitted else None,
    )


def _kit(track: str) -> InterviewKitRow:
    return InterviewKitRow(application_id=1, round=1, track=track, status="ready", questions=[])


def _on(track: str, uid: int, submitted: bool, round_number: int = 1) -> InterviewAssignment:
    row = _row(uid, submitted, round_number)
    row.track = track
    return row


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
    assert visible_sheets(rows, user=_user(9, Role.RECRUITER), current_round=1) == rows
    assert visible_sheets(rows, user=_user(9, Role.ADMIN), current_round=1) == rows


def test_assigned_interviewer_sees_only_own_sheet_until_submitted() -> None:
    rows = [_row(1, False), _row(2, True)]
    assert visible_sheets(rows, user=_user(1, Role.VIEWER), current_round=1) == [rows[0]]


def test_assigned_interviewer_sees_all_after_own_submit() -> None:
    """After submitting, drafts stay private to their author: row 2 (not
    submitted) stays hidden even though the caller has now submitted."""
    rows = [_row(1, True), _row(2, False), _row(3, True)]
    assert visible_sheets(rows, user=_user(1, Role.VIEWER), current_round=1) == [rows[0], rows[2]]


def test_unassigned_viewer_sees_no_sheets() -> None:
    rows = [_row(1, True), _row(2, True)]
    assert visible_sheets(rows, user=_user(3, Role.VIEWER), current_round=1) == []


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


def test_rows_in_round_selects_only_that_round() -> None:
    rows = [_row(1, True, 1), _row(2, False, 2), _row(1, False, 2)]
    assert rows_in_round(rows, 2) == [rows[1], rows[2]]
    assert rows_in_round(rows, 1) == [rows[0]]


def test_the_question_freeze_is_scoped_to_one_round() -> None:
    """Each round owns its questions now, so round one's submitted sheet
    does not freeze round two. Callers pass one round's rows."""
    rows = [_row(1, True, 1), _row(2, False, 2)]
    assert is_frozen(rows_in_round(rows, 1))
    assert not is_frozen(rows_in_round(rows, 2))


def test_round_completion_ignores_earlier_rounds() -> None:
    """Round 2 closes when round 2's sheets are in. Round 1's rows stay
    submitted forever and would otherwise close round 2 immediately."""
    rows = [_row(1, True, 1), _row(2, False, 2)]
    assert not all_submitted(rows_in_round(rows, 2))
    rows[1].submitted_at = datetime.now(UTC)
    assert all_submitted(rows_in_round(rows, 2))


def test_recruiter_sees_sheets_from_every_round() -> None:
    """Earlier rounds are the record of how the candidate got here."""
    rows = [_row(1, True, 1), _row(1, False, 2)]
    assert visible_sheets(rows, user=_user(9, Role.RECRUITER), current_round=2) == rows


def test_interviewer_sees_only_the_current_round() -> None:
    """Their own round-1 sheet is submitted, so the blind rule would happily
    reveal it — but showing round 1 back to them while they are judging
    round 2 is exactly the anchoring the blind rule exists to prevent."""
    rows = [_row(1, True, 1), _row(2, True, 1), _row(1, False, 2)]

    visible = visible_sheets(rows, user=_user(1, Role.VIEWER), current_round=2)

    assert visible == [rows[2]]


def test_rows_in_track_is_one_round_and_one_track() -> None:
    rows = [_on("tech", 1, False), _on("rh", 2, False), _on("tech", 3, False, round_number=2)]
    assert rows_in_track(rows, 1, "tech") == [rows[0]]
    assert rows_in_track(rows, 2, "tech") == [rows[2]]
    assert rows_in_track(rows, 1, "nope") == []


def test_a_round_closes_only_when_every_track_is_staffed_and_submitted() -> None:
    kits = [_kit("tech"), _kit("rh")]
    assert not round_complete([], [_on("tech", 1, True)]), "no kit: nothing to close"
    assert not round_complete(kits, []), "nobody assigned"
    assert not round_complete(kits, [_on("tech", 1, True)]), (
        "an unstaffed RH track must not be skipped when the technical panel finishes")
    assert not round_complete(kits, [_on("tech", 1, True), _on("rh", 2, False)])
    assert round_complete(kits, [_on("tech", 1, True), _on("rh", 2, True)])


def test_a_one_track_round_closes_as_before() -> None:
    one = [_kit("default")]
    assert round_complete(one, [_on("default", 1, True), _on("default", 2, True)])
    assert not round_complete(one, [_on("default", 1, True), _on("default", 2, False)])
