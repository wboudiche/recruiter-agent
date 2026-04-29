from pathlib import Path

import pytest

from recruiter.pipeline.parsers.docx import parse_docx

FIXTURE = Path(__file__).parent.parent / "fixtures/resumes/sample.docx"


def test_parse_docx_extracts_text() -> None:
    result = parse_docx(FIXTURE.read_bytes())
    assert "Alice Doe" in result.text
    assert "Rust" in result.text


def test_parse_docx_raises_on_invalid_bytes() -> None:
    with pytest.raises(ValueError, match="not a valid DOCX"):
        parse_docx(b"not a docx")
