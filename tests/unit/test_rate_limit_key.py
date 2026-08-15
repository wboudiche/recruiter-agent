"""Rate-limit keying must separate callers, not lump them together.

Two bugs made the 5/minute login cap behave as one shared bucket for the
whole deployment:

  1. nginx fronts the backend, and uvicorn was started without
     `--proxy-headers`, so `request.client.host` was the nginx container
     IP for every request — six people logging in within a minute meant
     the sixth got a 429.
  2. Every request keyed on IP alone, so colleagues behind one office NAT
     shared a budget even once (1) was fixed.

`rate_limit.py`'s own docstring anticipated this: "Keying is by remote IP
today; when auth lands, switch the key function to a per-principal
lookup." Auth has landed.
"""

from types import SimpleNamespace

from recruiter.api.rate_limit import client_key
from recruiter.auth.sessions import hash_token


def _request(cookies: dict[str, str] | None = None, host: str = "203.0.113.7"):
    """Minimal stand-in for the parts of Request that `client_key` reads."""
    return SimpleNamespace(
        cookies=cookies or {},
        client=SimpleNamespace(host=host, port=1234),
        headers={},
        scope={"type": "http", "client": (host, 1234), "headers": []},
    )


def test_unauthenticated_callers_are_keyed_by_address() -> None:
    """Login is unauthenticated, so the address is all there is."""
    assert client_key(_request(host="198.51.100.4")) == "198.51.100.4"


def test_two_sessions_behind_one_address_get_separate_budgets() -> None:
    """The office-NAT case: colleagues share a public IP, and one person's
    activity must not exhaust everyone else's allowance."""
    alice = client_key(_request({"recruiter_session": "alice-token"}, host="203.0.113.7"))
    bob = client_key(_request({"recruiter_session": "bob-token"}, host="203.0.113.7"))

    assert alice != bob


def test_one_session_keeps_its_budget_across_addresses() -> None:
    """A laptop moving from office wifi to a phone hotspot is the same
    principal and should not get a fresh allowance by changing network."""
    at_office = client_key(_request({"recruiter_session": "same-token"}, host="203.0.113.7"))
    on_mobile = client_key(_request({"recruiter_session": "same-token"}, host="198.51.100.9"))

    assert at_office == on_mobile


def test_the_session_token_never_appears_in_the_key() -> None:
    """Keys live in the limiter's store and surface in debugging output.
    A raw cookie there is a live credential; the hashed form is what the
    sessions table already stores."""
    token = "super-secret-session-token"
    key = client_key(_request({"recruiter_session": token}))

    assert token not in key
    assert hash_token(token) in key


def test_a_missing_client_does_not_crash() -> None:
    """ASGI scopes can carry no client (some test transports, some
    proxies). Rate limiting must degrade, not 500 the request."""
    request = _request()
    request.client = None
    request.scope = {"type": "http", "client": None, "headers": []}

    assert isinstance(client_key(request), str)
