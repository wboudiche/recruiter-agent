"""SlowAPI rate limiter shared across endpoints.

Single instance lives here so multiple routers can mount their own
@limiter.limit(...) decorators against the same key store.

Keying is per-principal where a principal exists, falling back to the
remote address for unauthenticated calls like login. Address-only keying
was wrong in two compounding ways:

  - nginx fronts the backend, so without `--proxy-headers` every request
    carried the nginx container's address and the entire deployment
    shared ONE bucket — six people logging in within a minute meant the
    sixth got a 429. (Fixed alongside this, in the Dockerfile CMD and the
    pinned compose subnet that makes the trust list deterministic.)
  - colleagues behind a single office NAT still share a public address,
    so one person's activity would exhaust everyone else's allowance.

The session cookie is the cheapest available principal: it is on the
request already, so no database round-trip happens inside the key
function (which SlowAPI calls synchronously, per request). It keys a
session rather than a user, so one person in two browsers gets two
budgets — an acceptable imprecision for throttling, and far closer than
one bucket for the whole company.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from recruiter.auth.sessions import hash_token
from recruiter.config import get_config


def client_key(request: Request) -> str:
    """Identify the caller for rate-limiting purposes.

    Returns the hashed session token when the caller is authenticated,
    otherwise their address. The token is hashed because limiter keys sit
    in the limiter's store and show up in debugging output — a raw cookie
    there is a live credential. `hash_token` is the same digest the
    `auth_sessions` table stores, so nothing new is invented here.
    """
    token = request.cookies.get("recruiter_session")
    if token:
        return f"session:{hash_token(token)}"
    # No client on the scope happens with some ASGI transports and
    # proxies. Degrade to a shared bucket rather than 500 the request:
    # throttling imprecisely beats refusing to serve.
    return get_remote_address(request) or "unknown"


limiter = Limiter(key_func=client_key)


def chat_rate_limit() -> str:
    """Effective rate limit string for POST /chat. Empty = disabled.

    SlowAPI's @limiter.limit accepts a callable, so the value is read at
    request time — env-var changes take effect on the next request without
    a process restart (during dev). Empty string falls back to a generous
    default that won't trip during tests.
    """
    return get_config().chat_rate_limit or "1000/minute"
