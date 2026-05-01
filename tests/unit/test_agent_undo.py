import time

import pytest

from recruiter.agent.undo import InMemoryUndoStore


def test_issue_and_consume() -> None:
    store = InMemoryUndoStore(ttl_seconds=60)
    token = store.issue(application_id=1, previous_stage="scored")
    assert isinstance(token, str) and len(token) >= 16
    payload = store.consume(token)
    assert payload == {"application_id": 1, "previous_stage": "scored"}


def test_consume_returns_none_for_unknown_token() -> None:
    store = InMemoryUndoStore(ttl_seconds=60)
    assert store.consume("does-not-exist") is None


def test_consume_is_one_shot() -> None:
    store = InMemoryUndoStore(ttl_seconds=60)
    token = store.issue(application_id=1, previous_stage="scored")
    assert store.consume(token) is not None
    assert store.consume(token) is None


def test_consume_after_ttl_returns_none() -> None:
    store = InMemoryUndoStore(ttl_seconds=0.01)
    token = store.issue(application_id=1, previous_stage="scored")
    time.sleep(0.05)
    assert store.consume(token) is None


def test_issue_with_payload_carries_extra_fields() -> None:
    store = InMemoryUndoStore(ttl_seconds=60)
    token = store.issue(
        application_id=42,
        payload={"previous_stage": "scored", "previous_validated_at": "2026-05-01T00:00:00+00:00"},
    )
    payload = store.consume(token)
    assert payload == {
        "application_id": 42,
        "previous_stage": "scored",
        "previous_validated_at": "2026-05-01T00:00:00+00:00",
    }


def test_consume_with_application_id_mismatch_does_not_burn_token() -> None:
    store = InMemoryUndoStore(ttl_seconds=60)
    token = store.issue(application_id=42, previous_stage="scored")
    # Wrong app id — should not consume.
    assert store.consume(token, application_id=99) is None
    # Right app id — token still works.
    payload = store.consume(token, application_id=42)
    assert payload is not None
    assert payload["application_id"] == 42


def test_consume_with_matching_application_id_succeeds() -> None:
    store = InMemoryUndoStore(ttl_seconds=60)
    token = store.issue(application_id=7, previous_stage="validated")
    payload = store.consume(token, application_id=7)
    assert payload == {"application_id": 7, "previous_stage": "validated"}
