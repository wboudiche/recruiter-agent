"""Rules for interviewer sheets, kept free of I/O so they are trivially testable.

Design: docs/superpowers/specs/2026-09-14-multi-interviewer-design.md.
"""
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.models import Application, InterviewAssignment, Role, Stage, User
from recruiter.models.interview_kit_row import InterviewKitRow
from recruiter.schemas.interview import InterviewSheet


def rows_in_round(
    rows: Iterable[InterviewAssignment], round_number: int,
) -> list[InterviewAssignment]:
    """The assignments belonging to one round, in their existing order."""
    return [r for r in rows if r.round == round_number]


def is_frozen(rows: Iterable[InterviewAssignment]) -> bool:
    """Once any sheet is submitted the question list must not lose rows,
    or submitted feedback would silently lose its answers.

    Scoped to ONE kit's rows: callers pass `rows_in_round(...)`. Each round
    owns its questions now, so a regeneration in round two cannot orphan
    round one's answers — the reason this once had to span every round.
    """
    return any(r.submitted_at is not None for r in rows)


def all_submitted(rows: Iterable[InterviewAssignment]) -> bool:
    """Whether every row given has been submitted. Callers pass ONE round's
    rows (see `rows_in_round`) — earlier rounds stay submitted forever and
    would otherwise close the new round the instant it opened."""
    rows = list(rows)
    return bool(rows) and all(r.submitted_at is not None for r in rows)


def can_edit_questions(user: User) -> bool:
    return user.role in (Role.ADMIN, Role.RECRUITER)


def visible_sheets(
    rows: Iterable[InterviewAssignment], *, user: User, current_round: int,
) -> list[InterviewAssignment]:
    """Blind until submitted: an interviewer sees only their own sheet
    until they submit. Submitting reveals their own sheet plus every OTHER
    sheet that has itself been submitted — drafts stay private to their
    author until submitted, even from someone who has already submitted
    their own. Recruiters and admins always see all; an unassigned viewer
    sees none.

    Recruiters and admins see every round, because earlier rounds are the
    record of how the candidate reached this one. An interviewer sees only
    the live round: their round-1 sheet is submitted, so the blind rule
    would happily hand it back to them, but replaying an earlier round
    while they judge this one is the anchoring the blind rule exists to
    prevent.
    """
    rows = list(rows)
    if can_edit_questions(user):
        return rows
    rows = rows_in_round(rows, current_round)
    own = next((r for r in rows if r.user_id == user.id), None)
    if own is None:
        return []
    if own.submitted_at is None:
        return [own]
    return [r for r in rows if r.user_id == own.user_id or r.submitted_at is not None]


def answered_question_ids(rows: Iterable[InterviewAssignment]) -> set[str]:
    """Every question id any interviewer has answered or rated.

    Fed to `merge_regenerated` so a regeneration keeps those questions with
    their ids intact. A sheet's answers are keyed by question id, so a
    regenerated probe with a fresh id silently orphans whatever was typed
    against the old one. The truthiness test matches `sheet_has_content`:
    the client posts a row per rendered question, so blank and untouched
    answers are the normal case and must not count.
    """
    out: set[str] = set()
    for row in rows:
        for qid, answer in ((row.sheet or {}).get("answers") or {}).items():
            if (answer or {}).get("answer") or (answer or {}).get("rating"):
                out.add(qid)
    return out


def prune_answers(sheet: InterviewSheet, question_ids: set[str]) -> InterviewSheet:
    """Drop answers for questions no longer in the kit. Dropping rather than
    rejecting means a recruiter removing a question while an interviewer is
    typing does not turn the interviewer's save into an error."""
    return sheet.model_copy(update={
        "answers": {k: v for k, v in sheet.answers.items() if k in question_ids},
    })


def sheet_has_content(sheet: dict) -> bool:
    """True if the sheet carries anything a recruiter would not want
    silently discarded: an answer, a rating, or a verdict decision/note.
    Used to refuse dropping an unsubmitted-but-populated interviewer from
    the panel instead of quietly deleting their draft."""
    answers = (sheet or {}).get("answers") or {}
    for answer in answers.values():
        if (answer or {}).get("answer") or (answer or {}).get("rating"):
            return True
    verdict = (sheet or {}).get("verdict") or {}
    return bool(verdict.get("decision") or verdict.get("note"))


def mark_interviewed(
    app_row: Application, kit_row: InterviewKitRow, now: datetime,
) -> None:
    """Close the round: move the application to INTERVIEWED and stamp the
    kit's closed_at. Shared by the automatic all-sheets-in rule
    (close_round_if_complete) and the recruiter's manual override in
    patch_application, so both paths stamp the same fields the same way."""
    app_row.stage = Stage.INTERVIEWED
    app_row.interviewed_at = now
    kit_row.closed_at = now.isoformat()


async def close_round_if_complete(session: AsyncSession, app_row: Application) -> bool:
    """Close the round if `app_row` is SCHEDULED, has a kit, and every
    assigned interviewer has submitted. Returns True iff it did.

    `app_row` must already be loaded with `with_for_update=True` by the
    caller — see submit_sheet's row-lock comment: two interviewers
    submitting their last two sheets at nearly the same instant would
    otherwise both read all_submitted() as True under READ COMMITTED and
    both try to close the round.

    `load_assignments` is imported here, not at module level: it lives in
    `api/interviewers.py`, a FastAPI router module, and that module needs
    `sheet_has_content` from this one for its own panel-edit checks —  a
    top-level import in both directions would be a cycle.
    """
    from recruiter.api.interviewers import load_assignments
    from recruiter.pipeline.kit_store import kit_for

    if app_row.stage != Stage.SCHEDULED:
        return False
    kit_row = await kit_for(session, app_row)
    if kit_row is None:
        return False
    rows = rows_in_round(
        await load_assignments(session, app_row.id), app_row.interview_round,
    )
    if not all_submitted(rows):
        return False
    mark_interviewed(app_row, kit_row, datetime.now(UTC))
    return True
