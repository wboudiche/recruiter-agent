from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

InputKind = Literal["github", "linkedin", "webpage", "paste", "pdf", "docx"]


@dataclass
class RoutedInput:
    kind: InputKind
    text: str | None
    source_url: str | None
    resume_path: str | None


def classify_url(url: str) -> InputKind:
    try:
        parsed = urlparse(url.strip())
    except Exception as exc:
        raise ValueError("invalid URL") from exc
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("invalid URL")
    host = parsed.netloc.lower().lstrip("www.")
    if host == "github.com":
        return "github"
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return "linkedin"
    return "webpage"
