"""Application logging setup.

`RECRUITER_LOG_LEVEL` has existed on `Config` (and been set to INFO in
`docker-compose.yml`) since before this module, but nothing ever applied
it. Without a `basicConfig`/`dictConfig` call, Python's root logger keeps
its default WARNING level and has no handler, so every `logger.info(...)`
in the codebase was discarded in the running container — including the
user-management audit trail, which is the only record of who promoted,
demoted, deactivated, or reset whom.

Uvicorn configures its own `uvicorn.*` loggers, which is why request
lines and startup banners appeared while application INFO did not, and
why the gap was easy to miss.
"""

import logging

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: str) -> None:
    """Point the root logger at stderr and set `level` on it.

    Tolerant of whatever an operator typed: the value arrives from an
    environment variable, so it may be lowercase or simply wrong. An
    unusable value falls back to INFO rather than raising during startup —
    losing the configured verbosity is bad, failing to boot over a typo in
    a log level is worse.

    Idempotent: calling it twice does not stack handlers, which would
    double-print every line.
    """
    resolved = logging.getLevelName(str(level).strip().upper())
    if not isinstance(resolved, int):
        resolved = logging.INFO

    root = logging.getLogger()
    root.setLevel(resolved)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(handler)
