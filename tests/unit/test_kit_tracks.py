import pytest
from fastapi import HTTPException

from recruiter.api.kit_tracks import adopt_orphan_rows, kit_for_caller, own_row, resolve_track
from recruiter.models import InterviewAssignment, InterviewKitRow, Role, User


def _kit(track: str) -> InterviewKitRow:
    return InterviewKitRow(application_id=1, round=1, track=track, status="ready", questions=[])


def _user(uid: int, role: Role) -> User:
    u = User(email=f"u{uid}@acme.com", role=role, is_active=True)
    u.id = uid
    return u


def _row(uid: int, track: str) -> InterviewAssignment:
    return InterviewAssignment(application_id=1, user_id=uid, round=1, track=track, sheet={})


def _status(fn, *args) -> int:
    with pytest.raises(HTTPException) as exc:
        fn(*args)
    return exc.value.status_code


def test_resolve_track() -> None:
    one, two = [_kit("default")], [_kit("tech"), _kit("rh")]
    assert resolve_track(one, None) is one[0], "one track: ?track= may be left out"
    assert resolve_track(two, "rh") is two[1]
    assert _status(resolve_track, two, None) == 422, "several tracks: ?track= required"
    assert _status(resolve_track, two, "nope") == 404
    assert _status(resolve_track, [], None) == 404


def test_own_row() -> None:
    rows = [_row(1, "tech"), _row(2, "rh")]
    assert own_row(rows, _user(2, Role.VIEWER)) is rows[1]
    assert own_row(rows, _user(3, Role.VIEWER)) is None


def test_an_interviewer_works_on_their_own_track_only() -> None:
    kits, rows = [_kit("tech"), _kit("rh")], [_row(2, "rh")]
    viewer = _user(2, Role.VIEWER)
    assert kit_for_caller(kits, rows, viewer, None) is kits[1], "no ?track= needed"
    assert kit_for_caller(kits, rows, viewer, "rh") is kits[1]
    assert _status(kit_for_caller, kits, rows, viewer, "tech") == 403
    assert _status(kit_for_caller, kits, rows, _user(9, Role.VIEWER), None) == 403


def test_a_recruiter_names_the_track() -> None:
    kits = [_kit("tech"), _kit("rh")]
    recruiter = _user(5, Role.RECRUITER)
    assert kit_for_caller(kits, [], recruiter, "tech") is kits[0]
    assert _status(kit_for_caller, kits, [], recruiter, None) == 422


def test_adopt_orphan_rows() -> None:
    kits = [_kit("t1"), _kit("t2")]
    orphan, staffed = _row(1, "default"), _row(2, "t2")
    adopt_orphan_rows(kits, [orphan, staffed])
    assert orphan.track == "t1", "a row on a track with no kit joins the round's first track"
    assert staffed.track == "t2", "a row already on a kit's track is untouched"


def test_adopt_orphan_rows_with_no_kits_changes_nothing() -> None:
    row = _row(1, "default")
    adopt_orphan_rows([], [row])
    assert row.track == "default"
