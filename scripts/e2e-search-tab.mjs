#!/usr/bin/env node
// Headed Playwright smoke for Plan G — full Search tab flow.
//
// Walks: /jobs/5 → Add candidate → Search tab → toggle GitHub →
//        type query → Search → cards stream in → click Add →
//        "Added ✓" appears → close → verify new card in Extracting.
//
// Prereqs (the running dev servers already satisfy these):
//   - Backend on http://localhost:8765 with dev-bypass auth
//   - Frontend on http://localhost:5173
//   - Job 5 exists ("Senior Java developer" — empty kanban)
//
// Run: node scripts/e2e-search-tab.mjs

import { chromium } from "playwright";

const FRONTEND = "http://localhost:5173";
const BACKEND = "http://localhost:8765";
const JOB_ID = 5;
const QUERY = "rust postgres";

function log(msg) {
  console.log(`[e2e] ${msg}`);
}

async function main() {
  // Snapshot Extracting count BEFORE the test so we can detect the new app.
  const before = await fetch(`${BACKEND}/api/jobs/${JOB_ID}/applications`)
    .then((r) => r.json())
    .then((rows) => rows.filter((r) => r.stage === "extracting").length);
  log(`Extracting column starts at ${before} cards on job ${JOB_ID}`);

  const browser = await chromium.launch({ headless: false, slowMo: 250 });
  const context = await browser.newContext();
  const page = await context.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") console.log(`[browser:error] ${msg.text()}`);
  });

  try {
    log(`Opening /jobs/${JOB_ID}`);
    await page.goto(`${FRONTEND}/jobs/${JOB_ID}`);
    await page.getByRole("button", { name: /add candidate/i }).click();

    log("Switching to Search tab");
    await page.getByRole("tab", { name: /^search$/i }).click();

    log("Toggling GitHub pill");
    await page.getByRole("button", { name: /^github$/i }).click();

    log(`Typing query: "${QUERY}"`);
    await page.getByPlaceholder(/senior rust/i).fill(QUERY);

    log("Clicking Search");
    await page.getByRole("button", { name: /^search$/i }).click();

    log("Waiting for first result card (up to 15s)");
    await page.getByRole("button", { name: /^add$/i }).first().waitFor({ timeout: 15000 });
    const cardCount = await page.getByRole("button", { name: /^add$/i }).count();
    log(`✓ ${cardCount} result cards rendered`);

    log("Clicking Add on the first card");
    await page.getByRole("button", { name: /^add$/i }).first().click();

    log("Waiting for 'Added ✓' state");
    await page.getByRole("button", { name: /added/i }).first().waitFor({ timeout: 5000 });
    log("✓ Button flipped to 'Added ✓'");

    log("Closing the slide-over");
    await page.keyboard.press("Escape");
    await page.waitForTimeout(500);

    log("Verifying new card appeared in Extracting");
    const after = await fetch(`${BACKEND}/api/jobs/${JOB_ID}/applications`)
      .then((r) => r.json())
      .then((rows) => rows.filter((r) => r.stage === "extracting").length);
    if (after !== before + 1) {
      throw new Error(`expected ${before + 1} extracting apps, got ${after}`);
    }
    log(`✓ Extracting count went from ${before} to ${after}`);

    log("ALL CHECKS PASSED");
    await page.waitForTimeout(2000);
  } catch (err) {
    console.error(`[e2e] FAIL: ${err.message}`);
    await page.screenshot({ path: "/tmp/e2e-search-tab-fail.png", fullPage: true });
    console.error("[e2e] screenshot saved to /tmp/e2e-search-tab-fail.png");
    process.exit(1);
  } finally {
    await browser.close();
  }
}

main();
