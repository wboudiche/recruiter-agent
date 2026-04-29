from recruiter.pipeline.fetchers.linkedin_stub import fetch_linkedin


def test_fetch_linkedin_returns_empty_text_with_url_metadata() -> None:
    result = fetch_linkedin("https://www.linkedin.com/in/alice/")
    assert result.text == ""
    assert result.metadata["needs_paste"] is True
    assert result.metadata["source_url"] == "https://www.linkedin.com/in/alice/"
