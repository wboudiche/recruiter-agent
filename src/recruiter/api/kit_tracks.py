"""Which track a kit request is about.

Recruiters and admins name a track with `?track=`; with one track in the
round it can be left out. An interviewer is on exactly one track per round,
so their track comes from their assignment and `?track=` may only repeat
it. Pure functions over already-loaded rows, so every router can share them
without importing each other.
"""
from fastapi import HTTPException

from recruiter.models import InterviewAssignment, InterviewKitRow, User
from recruiter.pipeline.interview_sheets import can_edit_questions


def resolve_track(kits: list[InterviewKitRow], requested: str | None) -> InterviewKitRow:
    """The kit `requested` names, or the round's only kit when it is None."""
    if not kits:
        raise HTTPException(status_code=404, detail="no interview kit; generate one first")
    if requested is not None:
        match = next((k for k in kits if k.track == requested), None)
        if match is None:
            raise HTTPException(status_code=404, detail=f"no track {requested!r} in this round")
        return match
    if len(kits) > 1:
        raise HTTPException(
            status_code=422, detail="this round has several tracks; name one with ?track=",
        )
    return kits[0]


def own_row(rows: list[InterviewAssignment], user: User) -> InterviewAssignment | None:
    """The caller's assignment among ONE round's rows."""
    return next((r for r in rows if r.user_id == user.id), None)


def kit_for_caller(
    kits: list[InterviewKitRow], rows: list[InterviewAssignment], user: User,
    requested: str | None,
) -> InterviewKitRow:
    """The kit a question edit or draft targets. Recruiters and admins:
    `resolve_track`. Anyone else must be on the round's panel (403) and
    works on their own track; naming another one is refused (403)."""
    if can_edit_questions(user):
        return resolve_track(kits, requested)
    own = own_row(rows, user)
    if own is None:
        raise HTTPException(status_code=403, detail="not assigned to this interview")
    if requested is not None and requested != own.track:
        raise HTTPException(status_code=403, detail="you are on another track")
    return resolve_track(kits, own.track)
