"""Headless LinkedIn login → extract `li_at` cookie.

Drives the login form via Playwright once, then returns the resulting
session cookie so the recruiter-agent can scrape profiles afterwards.

The user's password is held in memory only for the duration of this
call. It is never logged, never written to disk, never persisted in any
database column. Only the resulting cookie ends up in storage (and
that's encrypted via `settings_cipher`).

The result type distinguishes three outcomes so the API surface can
guide the user:
  - `connected(li_at)` — login succeeded, cookie ready to use.
  - `challenge(reason)` — LinkedIn intercepted with a verification step
    (email code, phone code, captcha). The caller should tell the user
    to log in once in their normal browser to clear the challenge, then
    retry.
  - `failed(reason)` — wrong password / account locked / network error.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass

from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

# A real modern Chrome UA. Headless Chromium otherwise advertises
# itself with "HeadlessChrome", which LinkedIn instantly fingerprints.
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)


def _stealth() -> Stealth:
    """Stealth config shared by validate_cookie + login flows."""
    return Stealth(
        navigator_user_agent_override=_USER_AGENT,
        navigator_platform_override="Linux x86_64",
        navigator_languages_override=("en-US", "en"),
    )


@dataclass(slots=True)
class LoginResult:
    status: str  # "connected" | "challenge" | "failed"
    li_at: str | None = None
    reason: str | None = None


async def validate_cookie(li_at: str, *, timeout_ms: int = 20000) -> LoginResult:
    """Lightweight check: does this `li_at` value land on /feed when
    Playwright opens linkedin.com with it injected?

    A valid cookie redirects to /feed; an invalid/expired one redirects
    to /login or /authwall. Faster than a full login flow (~5-10s).
    """
    if not li_at or not li_at.strip():
        return LoginResult(status="failed", reason="li_at value is empty")
    li_at = li_at.strip()

    async with _stealth().use_async(async_playwright()) as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            context = await browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1280, "height": 900},
                locale="en-US",
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
            try:
                await page.goto(
                    "https://www.linkedin.com/",
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )
            except PlaywrightTimeout:
                return LoginResult(status="failed", reason="LinkedIn timed out — try again")
            except PlaywrightError as exc:
                return LoginResult(
                    status="failed",
                    reason=f"browser error contacting LinkedIn: {type(exc).__name__}",
                )

            cur = (page.url or "").lower()
            if "/feed" in cur:
                return LoginResult(status="connected", li_at=li_at)
            if "/login" in cur or "/authwall" in cur or "/uas/login" in cur:
                return LoginResult(
                    status="failed",
                    reason="cookie rejected by LinkedIn — paste a fresh one",
                )
            # Any other landing page: assume cookie is OK (LinkedIn
            # sometimes lands on /checkpoint-clear or interstitials).
            return LoginResult(status="connected", li_at=li_at)
        finally:
            await browser.close()


async def login_and_extract_cookie(
    email: str,
    password: str,
    *,
    timeout_ms: int = 30000,
) -> LoginResult:
    """One-shot login: returns the `li_at` cookie or a failure reason.

    `password` is consumed immediately; the caller should hold the
    string only as long as needed and not log it.
    """
    if not email or not password:
        return LoginResult(status="failed", reason="email and password are required")

    async with _stealth().use_async(async_playwright()) as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            context = await browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1280, "height": 900},
                locale="en-US",
                timezone_id="Europe/Paris",
            )
            page = await context.new_page()
            try:
                await page.goto(
                    "https://www.linkedin.com/login",
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )
            except PlaywrightTimeout:
                return LoginResult(status="failed", reason="login page timed out")
            except PlaywrightError as exc:
                return LoginResult(
                    status="failed",
                    reason=f"browser error opening login page: {type(exc).__name__}",
                )

            # Polite typing delay so the form fields look human.
            try:
                await page.fill("#username", email)
                await asyncio.sleep(random.uniform(0.4, 0.9))
                await page.fill("#password", password)
                await asyncio.sleep(random.uniform(0.4, 0.9))
                # Submit + wait for either a new page or a same-page
                # challenge to render.
                async with page.expect_navigation(
                    wait_until="domcontentloaded", timeout=timeout_ms,
                ):
                    await page.click("button[type=submit]")
            except PlaywrightTimeout:
                # Some success paths return as an XHR + JS-side redirect
                # without a full navigation event — fall through and
                # inspect the URL anyway.
                pass
            except Exception as exc:
                logger.warning("linkedin login form error: %s", exc)
                return LoginResult(status="failed", reason=f"login error: {exc}")

            # Settle and inspect the final URL.
            await asyncio.sleep(random.uniform(1.0, 2.0))
            cur = (page.url or "").lower()

            if "/checkpoint" in cur or "/uas/login-submit" in cur \
                    or "/check/" in cur or "captcha" in cur:
                return LoginResult(
                    status="challenge",
                    reason=(
                        "LinkedIn presented a verification step "
                        "(email/phone code or captcha). Please log into "
                        "LinkedIn once from your normal browser to clear "
                        "the challenge, then retry."
                    ),
                )

            if "/login" in cur:
                # Still on /login means submit failed — usually wrong
                # password. Try to extract LinkedIn's own error text.
                err_text = ""
                try:
                    el = await page.query_selector("#error-for-password, .form__label--error")
                    if el is not None:
                        err_text = (await el.inner_text() or "").strip()
                except Exception:
                    pass
                return LoginResult(
                    status="failed",
                    reason=err_text or "login rejected — check your email/password",
                )

            # Extract the `li_at` cookie from the context.
            cookies = await context.cookies("https://www.linkedin.com")
            li_at = next(
                (c.get("value") for c in cookies if c.get("name") == "li_at"),
                None,
            )
            if not li_at:
                return LoginResult(
                    status="failed",
                    reason="login appeared to succeed but no li_at cookie was set",
                )
            return LoginResult(status="connected", li_at=li_at)
        finally:
            await browser.close()
