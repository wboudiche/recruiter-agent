from dataclasses import dataclass, field


@dataclass
class ParsedContent:
    text: str
    metadata: dict = field(default_factory=dict)


def parse_text(content: str) -> ParsedContent:
    return ParsedContent(text=content.strip(), metadata={})
