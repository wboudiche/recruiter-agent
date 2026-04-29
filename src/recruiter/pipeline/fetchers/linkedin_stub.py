from recruiter.pipeline.parsers.text import ParsedContent


def fetch_linkedin(url: str) -> ParsedContent:
    return ParsedContent(text="", metadata={"needs_paste": True, "source_url": url})
