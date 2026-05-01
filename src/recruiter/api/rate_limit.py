"""SlowAPI rate limiter shared across endpoints.

Single instance lives here so multiple routers can mount their own
@limiter.limit(...) decorators against the same key store. Keying is by
remote IP today (`get_remote_address`); when auth lands, switch the key
function to a per-principal lookup.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from recruiter.config import get_config

limiter = Limiter(key_func=get_remote_address)


def chat_rate_limit() -> str:
    """Effective rate limit string for POST /chat. Empty = disabled.

    SlowAPI's @limiter.limit accepts a callable, so the value is read at
    request time — env-var changes take effect on the next request without
    a process restart (during dev). Empty string falls back to a generous
    default that won't trip during tests.
    """
    return get_config().chat_rate_limit or "1000/minute"
