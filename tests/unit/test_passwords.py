"""The hashing wrapper is the only file that knows the algorithm.
Everything else calls these three functions."""

from recruiter.auth.passwords import (
    DUMMY_HASH,
    hash_password,
    needs_rehash,
    verify_password,
)


def test_hash_then_verify_roundtrips() -> None:
    hashed = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", hashed) is True


def test_wrong_password_is_rejected() -> None:
    hashed = hash_password("right")

    assert verify_password("wrong", hashed) is False


def test_hashes_are_salted() -> None:
    """Two users with the same password must not share a hash — otherwise
    a single crack, or even a glance at the column, reveals the collision."""
    assert hash_password("same") != hash_password("same")


def test_verify_against_missing_hash_is_false_not_an_error() -> None:
    """OIDC users have password_hash = NULL. The login path must treat that
    as 'wrong password', never as a crash or an accidental success."""
    assert verify_password("anything", None) is False


def test_dummy_hash_verifies_against_nothing() -> None:
    """DUMMY_HASH exists to burn the same CPU as a real verify on the
    unknown-email path, so timing cannot enumerate accounts."""
    assert verify_password("anything at all", DUMMY_HASH) is False


def test_needs_rehash_is_false_for_a_fresh_hash() -> None:
    assert needs_rehash(hash_password("fresh")) is False
