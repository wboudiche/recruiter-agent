"""Rules for interviewer sheets, kept free of I/O so they are trivially testable.

Design: docs/superpowers/specs/2026-09-14-multi-interviewer-design.md.
"""
from collections.abc import Iterable

from recruiter.models import InterviewAssignment, Role, User
from recruiter.schemas.interview import InterviewSheet


def is_frozen(rows: Iterable[InterviewAssignment]) -> bool:
    """Once any sheet is submitted the question list must not lose rows,
    or submitted feedback would silently lose its answers."""
    return any(r.submitted_at is not None for r in rows)


def all_submitted(rows: Iterable[InterviewAssignment]) -> bool:
    rows = list(rows)
    return bool(rows) and all(r.submitted_at is not None for r in rows)


def can_edit_questions(user: User) -> bool:
    return user.role in (Role.ADMIN, Role.RECRUITER)


def visible_sheets(
    rows: Iterable[InterviewAssignment], *, user: User,
) -> list[InterviewAssignment]:
    """Blind until submitted: an interviewer sees only their own sheet until
    they submit, then everyone's. Recruiters and admins always see all;
    an unassigned viewer sees none."""
    rows = list(rows)
    if can_edit_questions(user):
        return rows
    own = next((r for r in rows if r.user_id == user.id), None)
    if own is None:
        return []
    if own.submitted_at is None:
        return [own]
    return rows


def prune_answers(sheet: InterviewSheet, question_ids: set[str]) -> InterviewSheet:
    """Drop answers for questions no longer in the kit. Dropping rather than
    rejecting means a recruiter removing a question while an interviewer is
    typing does not turn the interviewer's save into an error."""
    return sheet.model_copy(update={
        "answers": {k: v for k, v in sheet.answers.items() if k in question_ids},
    })
