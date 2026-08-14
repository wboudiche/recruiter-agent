"""Password hashing. The ONLY module that knows which algorithm is used —
callers see three functions, so changing algorithm touches one file.

argon2id via argon2-cffi: OWASP's default recommendation, and it handles
salting, encoding, verification, and rehash detection itself rather than
leaving those to call sites.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()

# Burned on the unknown-email login path so that "no such user" costs the
# same wall-clock as "wrong password". Without it, ~1ms vs ~50ms tells an
# attacker which emails have accounts — reinstating the enumeration oracle
# that identical 401 bodies exist to close.
DUMMY_HASH = _hasher.hash("not-a-real-password")


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str | None) -> bool:
    """False rather than raising for every failure mode.

    `hashed` is None for OIDC users, who have no password. A malformed
    hash (hand-edited DB row) is also a failure, not a crash.
    """
    if not hashed:
        return False
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    try:
        return _hasher.check_needs_rehash(hashed)
    except InvalidHashError:
        return True
