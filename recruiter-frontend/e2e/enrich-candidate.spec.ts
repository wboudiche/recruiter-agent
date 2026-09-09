import { expect, test, type Page } from "@playwright/test";

interface JobSummary {
  id: number;
}
interface AppSummary {
  id: number;
  enrichment: Record<string, unknown> | null;
}

/** Enrichment fans out to GitHub, blogs, Twitter/X and Stack Exchange, gated
 *  by `enrichment.consent` and by which API keys happen to be configured. So
 *  this asserts what the app owes the recruiter regardless of which sources
 *  answered: an already-enriched candidate shows the bundle, and Re-enrich
 *  hands the work off to the backend. What the enrichers *find* is not
 *  something a test can pin down. */
async function findEnrichedApplication(
  page: Page,
): Promise<{ jobId: number; appId: number } | null> {
  const jobsResp = await page.request.get("/api/jobs");
  if (!jobsResp.ok()) return null;
  const jobs = (await jobsResp.json()) as JobSummary[];
  for (const job of jobs) {
    const appsResp = await page.request.get(`/api/jobs/${job.id}/applications`);
    if (!appsResp.ok()) continue;
    const apps = (await appsResp.json()) as AppSummary[];
    for (const app of apps) {
      const detail = await page.request.get(`/api/applications/${app.id}`);
      if (!detail.ok()) continue;
      const full = (await detail.json()) as AppSummary;
      if (full.enrichment) return { jobId: job.id, appId: app.id };
    }
  }
  return null;
}

test.describe("candidate enrichment", () => {
  test("an enriched candidate shows the enrichment section", async ({ page }) => {
    const found = await findEnrichedApplication(page);
    test.skip(found === null, "no enriched application in local DB");
    await page.goto(`/applications/${found!.appId}`);

    await expect(
      page.getByRole("heading", { name: "Enrichment", exact: true }),
    ).toBeVisible();
  });

  test("Re-enrich hands the candidate back to the pipeline", async ({ page }) => {
    const found = await findEnrichedApplication(page);
    test.skip(found === null, "no enriched application in local DB");
    await page.goto(`/applications/${found!.appId}`);

    const reEnrich = page.getByRole("button", { name: /re-enrich/i });
    await expect(reEnrich).toBeVisible();

    // 202: the endpoint clears the cached bundle and re-runs the pipeline from
    // Stage.ENRICHING in the background, so acceptance is the contract here —
    // not a finished bundle, which depends on live third-party sources.
    const responsePromise = page.waitForResponse(
      (r) =>
        r.url().includes(`/api/applications/${found!.appId}/re-enrich`) &&
        r.request().method() === "POST",
    );
    await reEnrich.click();
    const resp = await responsePromise;
    expect(resp.status()).toBe(202);
  });

  test("a failing re-enrich surfaces an error instead of failing silently", async ({ page }) => {
    const found = await findEnrichedApplication(page);
    test.skip(found === null, "no enriched application in local DB");
    await page.goto(`/applications/${found!.appId}`);

    await page.route(`**/api/applications/${found!.appId}/re-enrich`, (route) =>
      route.fulfill({
        status: 502,
        contentType: "application/json",
        body: JSON.stringify({ detail: "enrichment provider unavailable" }),
      }),
    );

    await page.getByRole("button", { name: /re-enrich/i }).click();

    // A rejected hand-off must reach the recruiter — a re-enrich that quietly
    // does nothing is indistinguishable from one that found nothing. Assert the
    // server's own `detail`, not a loose /error/i that any stray page text
    // could satisfy.
    await expect(
      page.getByText("enrichment provider unavailable").first(),
    ).toBeVisible({ timeout: 10_000 });
  });
});
