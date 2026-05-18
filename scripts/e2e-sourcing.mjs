#!/usr/bin/env node
// Headed Playwright smoke for Plan F.
//
// Prereqs (the dev backend + frontend started earlier already satisfy these):
//   - Backend running with dev-auth bypass on http://localhost:8765
//   - Frontend running on http://localhost:5173
//
// What this exercises (no Google CSE / Anthropic creds needed):
//   1. Settings → Sourcing tab renders and saves credentials
//   2. /api/settings round-trips the values (has_search_api_key flips to true)
//
// The full chat-search-and-add flow needs an Anthropic API key configured
// AND a Scored application in the DB; that's a separate test left for when
// you've got those in place. Run me with: node scripts/e2e-sourcing.mjs

import { chromium } from "playwright";

const FRONTEND = "http://localhost:5173";
const BACKEND = "http://localhost:8765";

function log(msg) {
  console.log(`[e2e] ${msg}`);
}

async function main() {
  const browser = await chromium.launch({
    headless: false,
    slowMo: 250, // slow enough to watch
  });
  const context = await browser.newContext();
  const page = await context.newPage();

  page.on("console", (msg) => {
    if (msg.type() === "error") console.log(`[browser:error] ${msg.text()}`);
  });

  try {
    log("Opening Settings → Sourcing");
    await page.goto(`${FRONTEND}/settings`);
    await page.getByRole("tab", { name: "Sourcing" }).click();

    log("Filling provider creds (dummy values — no real Google call)");
    // The provider Select already defaults to google_cse; just fill the inputs.
    await page.getByPlaceholder(/AIza/i).fill("AIzaSyDUMMYKEY_for_smoke_test");
    await page.getByPlaceholder(/abcd1234/i).fill("dummy:cseid12345");
    await page.getByPlaceholder(/ghp_/i).fill("ghp_dummy_token_for_smoke_test");

    log("Saving");
    await page.getByRole("button", { name: /^save$/i }).click();

    log("Waiting for success toast");
    await page.getByText(/sourcing settings saved/i).waitFor({ timeout: 5000 });
    log("✓ Toast appeared");

    log("Verifying /api/settings round-trip via fetch in the page context");
    const settings = await page.evaluate(async (apiBase) => {
      const r = await fetch(`${apiBase}/api/settings`, { credentials: "include" });
      return r.json();
    }, BACKEND);

    if (!settings.has_search_api_key) throw new Error("has_search_api_key did not flip to true");
    if (settings.search_engine_id !== "dummy:cseid12345") throw new Error(`CSE ID round-trip failed: got ${settings.search_engine_id}`);
    if (!settings.has_github_token) throw new Error("has_github_token did not flip to true");
    log(`✓ /api/settings has_search_api_key=${settings.has_search_api_key} engine=${settings.search_engine_id} has_github_token=${settings.has_github_token}`);

    log("Re-loading the page to verify the masked '(set)' placeholders");
    await page.goto(`${FRONTEND}/settings`);
    await page.getByRole("tab", { name: "Sourcing" }).click();

    const apiKeyPlaceholder = await page.getByPlaceholder(/\(set\)/i).count();
    if (apiKeyPlaceholder < 2) {
      throw new Error(`expected 2 '(set)' placeholders (api key + github token), found ${apiKeyPlaceholder}`);
    }
    log(`✓ ${apiKeyPlaceholder} '(set)' placeholders rendered`);

    log("ALL CHECKS PASSED");
    await page.waitForTimeout(2000); // small pause so you can see the final state
  } catch (err) {
    console.error(`[e2e] FAIL: ${err.message}`);
    await page.screenshot({ path: "/tmp/e2e-sourcing-fail.png" });
    console.error("[e2e] screenshot saved to /tmp/e2e-sourcing-fail.png");
    process.exit(1);
  } finally {
    await browser.close();
  }
}

main();
