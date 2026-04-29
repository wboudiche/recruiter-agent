from recruiter.pipeline.parsers.text import parse_text


def test_parse_text_preserves_internal_newlines() -> None:
    result = parse_text("Alice\nPython, Rust\n")
    assert result.text == "Alice\nPython, Rust"
    assert result.metadata == {}


def test_parse_text_strips_outer_whitespace() -> None:
    result = parse_text("   Alice\n  ")
    assert result.text == "Alice"
