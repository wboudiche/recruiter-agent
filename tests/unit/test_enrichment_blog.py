import httpx
import pytest

from recruiter.enrichment.blog import BlogProvider
from recruiter.enrichment.provider import EnrichmentHint


class FakeLLM:
    """Minimal stand-in for LLMClient.chat — returns a canned summary."""
    def __init__(self, output: str = "A blog about Rust async patterns.") -> None:
        self._output = output
        self.calls: list[list] = []

    async def chat(self, messages, *, system=None, max_tokens=2048, temperature=0.0):
        self.calls.append(messages)
        return self._output


def _make_provider(transport: httpx.MockTransport, llm=None) -> BlogProvider:
    return BlogProvider(llm=llm or FakeLLM(), transport=transport)


@pytest.mark.asyncio
async def test_enrich_html_page_returns_signal_with_summary() -> None:
    html = """
    <html><head><title>Alice's blog</title></head>
    <body>
      <h1>Async Rust patterns</h1>
      <p>Tokio gives you a runtime. lifetimes are the hard part.</p>
    </body></html>
    """
    handler = lambda req: httpx.Response(200, text=html, headers={"content-type": "text/html"})
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://alice.dev/posts/rust", confidence=1.0)
    r = await p.enrich(hint)
    assert r is not None
    assert r.source == "blog"
    assert r.profile_url == "https://alice.dev/posts/rust"
    assert len(r.signals) == 1
    assert r.signals[0].type == "writing"
    assert "Rust" in r.signals[0].summary or "blog" in r.signals[0].summary


@pytest.mark.asyncio
async def test_enrich_strips_html_tags_before_passing_to_llm() -> None:
    html = "<html><body><p>Hello <strong>world</strong></p><script>bad();</script></body></html>"
    handler = lambda req: httpx.Response(200, text=html, headers={"content-type": "text/html"})
    fake = FakeLLM()
    p = _make_provider(httpx.MockTransport(handler), llm=fake)
    hint = EnrichmentHint(url="https://alice.dev/", confidence=1.0)
    await p.enrich(hint)
    # The LLM input must not contain raw HTML or <script> contents.
    assert fake.calls
    sent = " ".join(m.content for m in fake.calls[-1])
    assert "<p>" not in sent
    assert "<script>" not in sent
    assert "bad();" not in sent


@pytest.mark.asyncio
async def test_enrich_returns_none_on_404() -> None:
    handler = lambda req: httpx.Response(404)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://alice.dev/missing", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_5xx() -> None:
    handler = lambda req: httpx.Response(503)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://alice.dev/", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_network_failure() -> None:
    def handler(req): raise httpx.ConnectError("refused", request=req)
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://alice.dev/", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_on_non_html_content_type() -> None:
    """A PDF / image / binary URL is not summarizable; skip rather than crash."""
    handler = lambda req: httpx.Response(
        200, content=b"%PDF-1.4...", headers={"content-type": "application/pdf"}
    )
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(url="https://alice.dev/cv.pdf", confidence=1.0)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_truncates_very_long_pages_before_llm() -> None:
    long_text = "<p>" + ("Rust async! " * 50000) + "</p>"
    handler = lambda req: httpx.Response(200, text=long_text, headers={"content-type": "text/html"})
    fake = FakeLLM()
    p = _make_provider(httpx.MockTransport(handler), llm=fake)
    hint = EnrichmentHint(url="https://alice.dev/", confidence=1.0)
    await p.enrich(hint)
    # The provider must cap the LLM input (the spec doesn't pin the
    # number, but it must be finite — pick 8000 chars).
    sent = " ".join(m.content for m in fake.calls[-1])
    assert len(sent) <= 12000   # 8000 content + headroom for the prompt template


@pytest.mark.asyncio
async def test_enrich_with_name_only_hint_returns_none() -> None:
    handler = lambda req: httpx.Response(200, text="x")
    p = _make_provider(httpx.MockTransport(handler))
    hint = EnrichmentHint(name="Alice Doe", confidence=0.5)
    assert await p.enrich(hint) is None


@pytest.mark.asyncio
async def test_enrich_returns_none_when_llm_summary_is_empty() -> None:
    """Empty LLM response → can't surface a useful signal → None."""
    html = "<html><body><p>Hi</p></body></html>"
    handler = lambda req: httpx.Response(200, text=html, headers={"content-type": "text/html"})
    fake = FakeLLM(output="   ")
    p = _make_provider(httpx.MockTransport(handler), llm=fake)
    hint = EnrichmentHint(url="https://alice.dev/", confidence=1.0)
    assert await p.enrich(hint) is None
