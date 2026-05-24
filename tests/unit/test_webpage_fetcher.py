import httpx
import pytest

from recruiter.pipeline.fetchers.webpage import fetch_webpage

SAMPLE_HTML = """
<!doctype html>
<html><head><title>Alice's Portfolio</title></head>
<body>
  <header>NAV</header>
  <article>
    <h1>Alice Doe</h1>
    <p>I'm a senior backend engineer working with Rust and Postgres.</p>
  </article>
  <footer>FOOTER</footer>
</body></html>
"""


@pytest.mark.asyncio
async def test_fetch_webpage_extracts_main_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=SAMPLE_HTML)

    transport = httpx.MockTransport(handler)
    result = await fetch_webpage("https://alice.dev", transport=transport)
    assert "Alice Doe" in result.text
    assert "Rust" in result.text
    assert result.metadata["source_url"] == "https://alice.dev"


@pytest.mark.asyncio
async def test_fetch_webpage_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    # The fetcher rewrites raw httpx errors into a recruiter-facing
    # message; assert on the HTTP status that's preserved in the text.
    with pytest.raises(ValueError, match="HTTP 404"):
        await fetch_webpage("https://nope.example", transport=transport)
