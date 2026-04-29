import io

from docx import Document
from docx.opc.exceptions import PackageNotFoundError

from recruiter.pipeline.parsers.text import ParsedContent


def parse_docx(data: bytes) -> ParsedContent:
    try:
        doc = Document(io.BytesIO(data))
    except PackageNotFoundError as exc:
        raise ValueError("not a valid DOCX") from exc
    paragraphs = [p.text for p in doc.paragraphs if p.text]
    return ParsedContent(text="\n".join(paragraphs).strip(), metadata={})
