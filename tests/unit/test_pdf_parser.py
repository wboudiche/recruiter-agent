from pathlib import Path

import pytest

from recruiter.pipeline.parsers.pdf import parse_pdf

FIXTURE = Path(__file__).parent.parent / "fixtures/resumes/sample.pdf"


def test_parse_pdf_extracts_text() -> None:
    result = parse_pdf(FIXTURE.read_bytes())
    assert "Alice Doe" in result.text
    assert "Python" in result.text
    assert result.metadata["page_count"] == 1


def test_parse_pdf_raises_on_invalid_bytes() -> None:
    with pytest.raises(ValueError, match="not a valid PDF"):
        parse_pdf(b"not a pdf")
