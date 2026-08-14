"""`RECRUITER_LOG_LEVEL` must actually take effect.

The setting existed and `docker-compose.yml` sets it to INFO, but nothing
ever applied it: with no `basicConfig`/`dictConfig`, Python's root logger
sits at WARNING, so every `logger.info(...)` in the codebase — including
the user-management audit trail, which is the only record of who promoted
or deactivated whom — was silently discarded in the running container.

Tests using `caplog` cannot catch this: pytest's capture attaches at the
logger and forces its own level, so an INFO line is visible to the test
suite whether or not it would ever reach a real handler. These tests
assert on the resulting configuration instead.
"""

import logging

from recruiter.logging_config import configure_logging


def test_configure_logging_applies_the_requested_level() -> None:
    root = logging.getLogger()
    original_level = root.level
    original_handlers = root.handlers[:]
    try:
        configure_logging("INFO")

        # An app logger must actually be enabled for INFO — this is what
        # was false before, and what made the audit trail invisible.
        assert logging.getLogger("recruiter.api.users").isEnabledFor(logging.INFO)
        assert root.handlers, "root logger needs a handler or records go nowhere"
    finally:
        root.setLevel(original_level)
        root.handlers[:] = original_handlers


def test_configure_logging_accepts_lowercase_and_unknown_levels() -> None:
    """The value comes from an env var a human typed, so it may be
    lowercase or nonsense. Neither should crash the app at startup."""
    root = logging.getLogger()
    original_level = root.level
    original_handlers = root.handlers[:]
    try:
        configure_logging("debug")
        assert logging.getLogger("recruiter").isEnabledFor(logging.DEBUG)

        configure_logging("not-a-level")
        # Falls back to INFO rather than raising.
        assert logging.getLogger("recruiter").isEnabledFor(logging.INFO)
    finally:
        root.setLevel(original_level)
        root.handlers[:] = original_handlers


def test_configure_logging_is_idempotent() -> None:
    """Called twice (import plus lifespan, or a test re-import), it must
    not stack duplicate handlers — that double-prints every log line."""
    root = logging.getLogger()
    original_level = root.level
    original_handlers = root.handlers[:]
    try:
        configure_logging("INFO")
        first = len(root.handlers)
        configure_logging("INFO")

        assert len(root.handlers) == first
    finally:
        root.setLevel(original_level)
        root.handlers[:] = original_handlers
