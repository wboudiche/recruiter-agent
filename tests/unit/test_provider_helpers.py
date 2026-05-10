import pytest

from recruiter.sourcing.provider import parse_linkedin_name


@pytest.mark.parametrize("title,expected", [
    ("Alice Doe - Senior Rust Engineer | LinkedIn", "Alice Doe"),
    ("Bob | LinkedIn", "Bob"),
    ("  Carol Smith  - VP", "Carol Smith"),
    ("Dan", "Dan"),
])
def test_parse_linkedin_name_extracts_name(title: str, expected: str) -> None:
    assert parse_linkedin_name(title) == expected


@pytest.mark.parametrize("title", [None, "", "   "])
def test_parse_linkedin_name_returns_none_for_empty(title: str | None) -> None:
    assert parse_linkedin_name(title) is None
