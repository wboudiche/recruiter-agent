"""Headless-Chromium LinkedIn profile fetcher.

This module exists because LinkedIn intentionally blocks plain HTTP
scraping — Trafilatura on the public stub returns nothing useful. To get
the actual profile body (experience, education, skills sections) we
launch Chromium with the operator's logged-in `li_at` session cookie,
let the page render, and grab the visible body text.

**Operational warnings**
- Uses the operator's LinkedIn account credentials (cookie). LinkedIn's
  anti-bot stack may challenge or temporarily ban that account if the
  call pattern looks robotic. Polite delays + a real user-agent are the
  best defence; nothing prevents detection entirely.
- Violates LinkedIn's User Agreement. Fine for an internal recruiter
  tool used by a single person; not appropriate for a customer-facing
  multi-tenant product.

**Failure modes**
- No cookie configured → returns empty text + `needs_paste=True` so the
  caller falls back to the GitHub-by-name enricher / manual paste flow.
- Cookie expired / challenged / banned → LinkedIn redirects to
  `/login`, `/checkpoint`, or `/authwall`. Detected via URL match;
  same fallback applies.
- Page timeout / network error → same fallback.
"""

from __future__ import annotations

import asyncio
import logging
import random
from urllib.parse import urlparse

from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)
from playwright_stealth import Stealth

from recruiter.pipeline.parsers.text import ParsedContent

logger = logging.getLogger(__name__)

# A real modern Chrome UA. Headless Chromium otherwise advertises itself
# with "HeadlessChrome", which LinkedIn instantly fingerprints.
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)


def _flag(reason: str, url: str) -> ParsedContent:
    return ParsedContent(
        text="",
        metadata={"needs_paste": True, "reason": reason, "source_url": url},
    )


async def fetch_linkedin_playwright(
    url: str,
    *,
    li_at: str,
    timeout_ms: int = 30000,
) -> ParsedContent:
    """Fetch a LinkedIn profile via headless Chromium.

    Returns the visible body text. Empty text + `needs_paste=True` if no
    cookie was provided, the cookie was rejected, or the page failed to
    load — the caller's existing fallback path then takes over.
    """
    if not li_at:
        return _flag("no li_at cookie configured", url)

    parsed = urlparse(url)
    if "linkedin.com" not in (parsed.netloc or "").lower():
        raise ValueError(f"not a linkedin URL: {url}")

    # `Stealth(...).use_async(async_playwright())` patches the
    # context manager so every page/browser produced inside picks up
    # the anti-detection scripts (navigator.webdriver, WebGL params,
    # missing chrome.runtime, plugins, etc.) — needed because LinkedIn
    # detects headless Chromium and serves a degraded "Limited public"
    # view otherwise.
    stealth = Stealth(
        navigator_user_agent_override=_USER_AGENT,
        navigator_platform_override="Linux x86_64",
        navigator_languages_override=("en-US", "en"),
    )
    async with stealth.use_async(async_playwright()) as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            context = await browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1280, "height": 900},
                locale="en-US",
                timezone_id="Europe/Paris",
            )
            await context.add_cookies([{
                "name": "li_at",
                "value": li_at,
                "domain": ".linkedin.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "sameSite": "None",
            }])
            page = await context.new_page()

            # Polite pre-nav delay — looks more human than instant requests.
            await asyncio.sleep(random.uniform(1.5, 3.0))

            try:
                # `networkidle` waits until the page has had a 500ms quiet
                # window — important because LinkedIn lazy-fetches the
                # experience / education sections via async XHRs after
                # initial DOMContentLoaded. With `domcontentloaded` alone
                # we frequently capture only the header.
                await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            except PlaywrightTimeout:
                # networkidle can time out on chatty pages — fall back
                # to whatever rendered.
                logger.info("linkedin networkidle timeout for %s — continuing", url)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
                except PlaywrightTimeout:
                    return _flag("page timeout", url)
            except PlaywrightError as exc:
                # Browser-level errors: ERR_TOO_MANY_REDIRECTS (cookie
                # invalid → bounce loop), ERR_NAME_NOT_RESOLVED, etc.
                # These would otherwise bubble up as 500s. Surface as
                # `needs_paste` so the caller falls back cleanly.
                logger.warning("linkedin nav error for %s: %s", url, exc)
                return _flag(f"browser error: {type(exc).__name__}", url)

            cur = (page.url or "").lower()
            if any(seg in cur for seg in ("/login", "/checkpoint", "/authwall", "/uas/login")):
                logger.warning(
                    "linkedin redirected to %s — cookie likely expired or challenged",
                    page.url,
                )
                return _flag("cookie expired or challenged", url)

            # LinkedIn lazy-loads experience/education/skills sections
            # on scroll AND collapses long lists behind "voir plus" /
            # "show more" buttons. A single scroll-to-bottom misses
            # everything below the fold. Strategy:
            #
            #   1. Progressive scroll in ~12% increments so each section
            #      enters the viewport long enough to fire its lazy load.
            #   2. Wait for `networkidle` once to let the initial XHRs
            #      that fetch each section settle.
            #   3. Click every visible "voir plus" / "show more" /
            #      "Show all positions" expander button — repeat the
            #      pass because new buttons appear after expansion.
            #   4. Final scroll-to-top + brief wait + capture.
            try:
                # Best-effort wait for any LinkedIn section header to
                # appear in the DOM. If the page rendered as the
                # "limited public" view (header only, no sections),
                # this selector never matches — that's fine, we proceed
                # with whatever's there.
                try:
                    await page.wait_for_function(
                        """() => {
                            const t = document.body.innerText || '';
                            return /\\b(Expérience|Experience|Formation|Education|Compétences|Skills)\\b/.test(t);
                        }""",
                        timeout=5000,
                    )
                except PlaywrightTimeout:
                    pass

                # Step 1: progressive scroll (8 stops top → bottom).
                for frac in (0.12, 0.25, 0.4, 0.55, 0.7, 0.85, 1.0):
                    await page.evaluate(
                        f"window.scrollTo({{ top: document.body.scrollHeight * {frac}, behavior: 'instant' }})"
                    )
                    await asyncio.sleep(random.uniform(0.45, 0.75))

                # Step 2: best-effort networkidle wait (capped — many
                # LinkedIn pages keep some background pings open
                # indefinitely, so this is allowed to time out).
                try:
                    await page.wait_for_load_state("networkidle", timeout=4000)
                except PlaywrightTimeout:
                    pass

                # Step 3: click expanders. Two passes — the second
                # pass catches "see all 12 experiences" buttons that
                # only render once the section is in view.
                expander_re = (
                    r"^("
                    r"voir plus|afficher plus|"
                    r"see more|show more|"
                    r"voir tout|voir les \\d+|"
                    r"show all|"
                    r"\\.\\.\\.\\s*voir plus"
                    r")$"
                )
                for _ in range(2):
                    clicked = await page.evaluate(
                        """(re) => {
                            const rx = new RegExp(re, 'i');
                            const btns = Array.from(document.querySelectorAll(
                                'button, a[role=button], span[role=button]'
                            ));
                            let n = 0;
                            for (const b of btns) {
                                const t = (b.innerText || b.textContent || '').trim();
                                if (!t) continue;
                                if (rx.test(t) || /voir plus/i.test(t) || /show more/i.test(t)) {
                                    try { b.click(); n++; } catch {}
                                }
                            }
                            return n;
                        }""",
                        expander_re,
                    )
                    if not clicked:
                        break
                    await asyncio.sleep(random.uniform(0.6, 1.1))

                # Step 4: scroll back to top, settle, capture.
                await page.evaluate("window.scrollTo(0, 0)")
                await asyncio.sleep(random.uniform(0.5, 1.0))
                body_text = await page.evaluate("document.body.innerText")
            except Exception as exc:  # page closed mid-flight, JS error, etc.
                logger.warning("linkedin DOM read failed for %s: %s", url, exc)
                return _flag("dom read failed", url)

            text = (body_text or "").strip()
            if not text:
                return _flag("empty body", url)

            return ParsedContent(
                text=text,
                metadata={"source_url": url, "scraper": "playwright"},
            )
        finally:
            await browser.close()
