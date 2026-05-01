import time

import pytest

from recruiter.agent.undo import UndoStore


def test_issue_and_consume() -> None:
    store = UndoStore(ttl_seconds=60)
    token = store.issue(application_id=1, previous_stage="scored")
    assert isinstance(token, str) and len(token) >= 16
    payload = store.consume(token)
    assert payload == {"application_id": 1, "previous_stage": "scored"}


def test_consume_returns_none_for_unknown_token() -> None:
    store = UndoStore(ttl_seconds=60)
    assert store.consume("does-not-exist") is None


def test_consume_is_one_shot() -> None:
    store = UndoStore(ttl_seconds=60)
    token = store.issue(application_id=1, previous_stage="scored")
    assert store.consume(token) is not None
    assert store.consume(token) is None


def test_consume_after_ttl_returns_none() -> None:
    store = UndoStore(ttl_seconds=0.01)
    token = store.issue(application_id=1, previous_stage="scored")
    time.sleep(0.05)
    assert store.consume(token) is None
