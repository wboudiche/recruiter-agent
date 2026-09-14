import { expect, test, type Page } from "@playwright/test";

/** Phone-width layout: no page must scroll horizontally.
 *
 *  Measured leaf-by-leaf at 400px before this spec existed, the header nav
 *  (user chip + links) overflowed on every route, the job page toolbar by
 *  600px+, and the settings tab strip by ~260px. Each is a row that could
 *  not wrap or shrink. Asserting on the document's scroll width catches
 *  any of them — and the next one — without pinning a selector. */
test.use({ viewport: { width: 400, height: 850 } });

async function pageOverflowPx(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

async function expectNoHorizontalScroll(page: Page, path: string) {
  await page.goto(path);
  // Wait for the route's content, not just the shell.
  await expect(page.locator("main")).not.toContainText(/loading…/i, { timeout: 15_000 });
  await page.waitForTimeout(500); // fonts + layout settle
  expect(await pageOverflowPx(page), `${path} scrolls horizontally`).toBeLessThanOrEqual(0);
}

test.describe("phone width (400px)", () => {
  test("jobs list, new job and settings fit the viewport", async ({ page }) => {
    for (const path of ["/jobs", "/jobs/new", "/settings"]) {
      await expectNoHorizontalScroll(page, path);
    }
  });

  test("job kanban and candidate detail fit the viewport", async ({ page }) => {
    // Self-discovering, like the other specs: any existing job with at
    // least one application will do.
    const jobs = await (await page.request.get("/api/jobs")).json();
    test.skip(jobs.length === 0, "needs at least one job");
    let appId: number | null = null;
    let jobId: number = jobs[0].id;
    for (const job of jobs) {
      const apps = await (await page.request.get(`/api/jobs/${job.id}/applications`)).json();
      if (apps.length > 0) { jobId = job.id; appId = apps[0].id; break; }
    }
    await expectNoHorizontalScroll(page, `/jobs/${jobId}`);
    test.skip(appId === null, "needs at least one application");
    await expectNoHorizontalScroll(page, `/applications/${appId}`);
    await expectNoHorizontalScroll(page, `/applications/${appId}?tab=interview`);
  });
});
