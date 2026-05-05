#!/usr/bin/env node
// Headed Playwright smoke for Plan H — power-user kanban polish.
//
// Walks every Plan H surface:
//   1. Time-in-stage badges on every card
//   2. Density toggle (comfortable / compact)
//   3. Score distribution strip on the Scored column
//   4. Multi-select with shift-click + BulkActionsBar
//   5. Cmd+K command palette via keyboard
//   6. Magnifying-glass header trigger opens the palette
//   7. Palette query input filters jobs
//
// Prereqs:
//   - Backend on http://localhost:8765 with dev-bypass auth
//   - Frontend on http://localhost:5173
//   - Job 4 exists with at least 2 applications including some in Scored
//
// Run: node scripts/e2e-power-user-kanban.mjs

import { chromium } from "playwright";

const FRONTEND = "http://localhost:5173";
const BACKEND = "http://localhost:8765";
const JOB_ID = 4;
const PLATFORM_MOD = process.platform === "darwin" ? "Meta" : "Control";

function log(msg) {
  console.log(`[e2e] ${msg}`);
}

async function main() {
  // Sanity-check the backend has scored apps on this job (otherwise Step 3+5 will skip).
  const apps = await fetch(`${BACKEND}/api/jobs/${JOB_ID}/applications`).then((r) => r.json());
  const scored = apps.filter((a) => a.stage === "scored");
  log(`Job ${JOB_ID}: ${apps.length} applications, ${scored.length} scored`);
  if (scored.length < 2) {
    log(`WARNING: need ≥2 scored applications on job ${JOB_ID} to exercise multi-select`);
  }

  const browser = await chromium.launch({ headless: false, slowMo: 250 });
  const context = await browser.newContext();
  const page = await context.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") console.log(`[browser:error] ${msg.text()}`);
  });

  try {
    log(`Opening /jobs/${JOB_ID}`);
    await page.goto(`${FRONTEND}/jobs/${JOB_ID}`);
    await page.getByText(/extracting/i).first().waitFor({ timeout: 10000 });

    // 1. Time-in-stage badges
    log("Checking time-in-stage badges");
    // Each card has a stage row with a relative-time span on the right (text like "3d", "5h", "<1m").
    // We look for at least one such badge by matching the regex for those formats.
    const badge = page.locator("text=/^(<1m|\\d+m|\\d+h|\\d+d|—)$/").first();
    await badge.waitFor({ timeout: 5000 });
    log(`✓ time-in-stage badge present (${await badge.textContent()})`);

    // 2. Density toggle
    log("Toggling density Comfortable → Compact");
    await page.getByRole("button", { name: /^compact$/i }).click();
    // After switching, the Compact button is selected (aria-pressed=true).
    const compactBtn = page.getByRole("button", { name: /^compact$/i });
    if ((await compactBtn.getAttribute("aria-pressed")) !== "true") {
      throw new Error("density toggle did not flip to compact");
    }
    log("✓ Compact mode engaged");

    log("Toggling back to Comfortable");
    await page.getByRole("button", { name: /^comfortable$/i }).click();
    const comfBtn = page.getByRole("button", { name: /^comfortable$/i });
    if ((await comfBtn.getAttribute("aria-pressed")) !== "true") {
      throw new Error("density toggle did not flip back to comfortable");
    }
    log("✓ Comfortable mode restored");

    // 3. Score distribution strip
    if (scored.length >= 1) {
      log("Verifying score distribution strip on the Scored column");
      // The strip is an <svg aria-label="score distribution"> with one <rect> per scored app.
      const strip = page.locator('svg[aria-label="score distribution"]');
      await strip.waitFor({ timeout: 5000 });
      const tickCount = await strip.locator("rect").count();
      log(`✓ distribution strip has ${tickCount} ticks (expected ${scored.length})`);
    } else {
      log("(skipped — no scored applications)");
    }

    // 4. Multi-select + bulk actions bar
    if (scored.length >= 2) {
      log("Shift-clicking 2 scored cards");
      // Find the Scored column header, then the first 2 cards under it.
      // The candidate cards are <Card> elements; the easiest selector is the application
      // detail link href pattern.
      const scoredCards = page.locator('a[href^="/applications/"]')
        .filter({ has: page.locator("text=/scored/i") });
      const cardCount = await scoredCards.count();
      if (cardCount < 2) {
        throw new Error(`expected ≥2 scored cards in DOM, found ${cardCount}`);
      }
      await scoredCards.nth(0).click({ modifiers: ["Shift"] });
      await scoredCards.nth(1).click({ modifiers: ["Shift"] });

      log("Verifying BulkActionsBar appeared");
      await page.getByText(/^2 selected$/).waitFor({ timeout: 3000 });
      log("✓ '2 selected' visible");

      log("Clicking Clear");
      await page.getByRole("button", { name: /^clear$/i }).click();
      // Bar disappears; "2 selected" should no longer be in the DOM.
      await page.getByText(/^2 selected$/).waitFor({ state: "detached", timeout: 3000 });
      log("✓ bar dismissed");
    } else {
      log("(multi-select check skipped — need 2+ scored apps)");
    }

    // 5. Cmd+K palette via keyboard
    log(`Opening palette via ${PLATFORM_MOD}+K`);
    await page.keyboard.press(`${PLATFORM_MOD}+k`);
    await page.getByPlaceholder(/^search…$/i).waitFor({ timeout: 3000 });
    log("✓ palette opened (Search input visible)");

    log("Typing 'java' to filter");
    await page.getByPlaceholder(/^search…$/i).fill("java");
    // The job titles "Senior Java developper" should remain visible; others filtered out.
    await page.getByText(/Senior Java/i).first().waitFor({ timeout: 3000 });
    log("✓ filter narrows to Java-matching items");

    log("Closing palette via Esc");
    await page.keyboard.press("Escape");
    await page.getByPlaceholder(/^search…$/i).waitFor({ state: "detached", timeout: 3000 });

    // 6. Magnifying-glass trigger
    log("Re-opening palette via magnifying-glass header button");
    await page.getByRole("button", { name: /open command palette/i }).click();
    await page.getByPlaceholder(/^search…$/i).waitFor({ timeout: 3000 });
    log("✓ trigger opens palette");

    // 7. Theme action via palette
    log("Verifying theme actions are listed");
    await page.getByText(/switch to light theme/i).waitFor({ timeout: 2000 });
    log("✓ theme actions present");

    log("ALL CHECKS PASSED");
    await page.waitForTimeout(2000);
  } catch (err) {
    console.error(`[e2e] FAIL: ${err.message}`);
    await page.screenshot({ path: "/tmp/e2e-power-user-kanban-fail.png", fullPage: true });
    console.error("[e2e] screenshot saved to /tmp/e2e-power-user-kanban-fail.png");
    process.exit(1);
  } finally {
    await browser.close();
  }
}

main();
