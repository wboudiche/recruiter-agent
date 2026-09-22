"""A round's tracks: made when a round starts, reconciled when the same
round is scheduled again, carried into the next round.

Design: docs/superpowers/specs/2026-09-22-interview-tracks-design.md. Every
function here runs inside `patch_application` (or the tracks router) under
the application row lock its caller took. Those that start tracks return
the keys whose generation must be dispatched after the commit (see
api/interview.dispatch_generation).
"""
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.interviewers import load_assignments
from recruiter.api.kit_tracks import adopt_orphan_rows
from recruiter.models import Application, InterviewAssignment, InterviewKitRow, InterviewTemplate
from recruiter.models.interview_assignment import empty_sheet
from recruiter.pipeline.interview_sheets import is_frozen, rows_in_round, sheet_has_content
from recruiter.pipeline.kit_store import create_kit, kits_in_round, template_fields, track_key


def _key(template: InterviewTemplate | None) -> str:
    return track_key(template.id if template is not None else None)


async def create_track(
    session: AsyncSession, app_row: Application, template: InterviewTemplate | None,
    now: datetime,
) -> InterviewKitRow:
    """A new track in the live round: its kit, pending generation."""
    kit = await create_kit(
        session, app_row, round=app_row.interview_round, track=_key(template),
        status="generating", **template_fields(template),
    )
    # Pairs with generate_kit's in-flight check, so a manual Generate
    # during this run is a no-op rather than a second model call.
    kit.generating_since = now.isoformat()
    return kit


async def start_round(
    session: AsyncSession, app_row: Application,
    choices: list[InterviewTemplate | None], now: datetime,
) -> list[str]:
    """Scheduling the live round, first time or again (reject → re-invite →
    schedule keeps the round number).

    Each chosen template's track: absent → created; frozen with questions →
    left as it is, a stuck `error`/`generating` kit recovered to `ready`
    (regenerating would orphan submitted answers); otherwise regenerated,
    which keeps answered questions (run_generate_kit). Tracks not chosen are
    removed with their panel rows when nobody on them has written anything,
    and kept otherwise.
    """
    rows = rows_in_round(
        await load_assignments(session, app_row.id), app_row.interview_round,
    )
    existing = {k.track: k for k in await kits_in_round(session, app_row)}
    wanted = {_key(t) for t in choices}
    to_generate: list[str] = []
    for template in choices:
        key = _key(template)
        kit = existing.get(key)
        if kit is None:
            await create_track(session, app_row, template, now)
            to_generate.append(key)
            continue
        if is_frozen(r for r in rows if r.track == key) and kit.questions:
            if kit.status != "ready":
                kit.status = "ready"
                kit.error = None
            continue
        kit.status = "generating"
        kit.error = None
        kit.generating_since = now.isoformat()
        to_generate.append(key)
    for key, kit in existing.items():
        if key in wanted:
            continue
        panel = [r for r in rows if r.track == key]
        if any(r.submitted_at is not None or sheet_has_content(r.sheet) for r in panel):
            continue
        for row in panel:
            await session.delete(row)
        await session.delete(kit)
    await session.flush()
    adopt_orphan_rows(
        await kits_in_round(session, app_row),
        rows_in_round(await load_assignments(session, app_row.id), app_row.interview_round),
    )
    return to_generate


async def open_next_round(
    session: AsyncSession, app_row: Application,
    choices: list[InterviewTemplate | None], now: datetime,
) -> list[str]:
    """Reopen an interviewed application for another round, one track per
    choice.

    A choice the closing round also used (matched by template, no template
    matching no template) copies that track forward: questions, snapshot,
    status and error, plus its panel on empty sheets. Any other choice
    starts a fresh track, generated, with no panel. Tracks of the closing
    round that were not chosen stay in its history.
    """
    previous_round = app_row.interview_round
    previous_rows = rows_in_round(await load_assignments(session, app_row.id), previous_round)
    previous = {k.template_id: k for k in await kits_in_round(session, app_row)}

    app_row.interview_round = previous_round + 1
    # The round is open again, so the application is no longer interviewed.
    app_row.interviewed_at = None

    if not previous and choices == [None]:
        # A round that never had a kit, reopened with no template: as before
        # tracks, the panel carries over and no kit is made.
        for row in previous_rows:
            session.add(InterviewAssignment(
                application_id=app_row.id, user_id=row.user_id,
                round=app_row.interview_round, track=row.track, sheet=empty_sheet(),
            ))
        return []

    to_generate: list[str] = []
    for template in choices:
        before = previous.get(template.id if template is not None else None)
        if before is None:
            await create_track(session, app_row, template, now)
            to_generate.append(_key(template))
            continue
        # Carry the previous kit's status and error forward rather than
        # forcing "ready": a round stuck in "error" must stay visibly broken
        # on reopen too, or the recruiter sees an empty ready kit with the
        # failure hidden instead of a reason to regenerate it.
        await create_kit(
            session, app_row, round=app_row.interview_round, track=before.track,
            questions=list(before.questions or []),
            status=before.status, error=before.error,
            template_id=before.template_id, template_name=before.template_name,
            template_snapshot=before.template_snapshot,
        )
        for row in previous_rows:
            if row.track == before.track:
                session.add(InterviewAssignment(
                    application_id=app_row.id, user_id=row.user_id,
                    round=app_row.interview_round, track=before.track, sheet=empty_sheet(),
                ))
    return to_generate
