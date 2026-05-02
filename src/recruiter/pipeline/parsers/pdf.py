import fitz  # type: ignore[import-untyped]  # PyMuPDF — no published stubs

from recruiter.pipeline.parsers.text import ParsedContent


def parse_pdf(data: bytes) -> ParsedContent:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ValueError("not a valid PDF") from exc
    try:
        chunks = [page.get_text("text") for page in doc]
        text = "\n".join(chunks).strip()
        return ParsedContent(text=text, metadata={"page_count": doc.page_count})
    finally:
        doc.close()
