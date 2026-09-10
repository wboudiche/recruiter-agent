import { expect, test, type Page } from "@playwright/test";

interface JobSummary { id: number }
interface AppSummary { id: number; stage: string }

/** A candidate sitting at `scheduled` is what this flow needs; the kit is
 *  generated on entering that stage. */
async function findScheduledApplication(
  page: Page,
): Promise<{ jobId: number; appId: number } | null> {
  const jobs = (await (await page.request.get("/api/jobs")).json()) as JobSummary[];
  for (const job of jobs) {
    const apps = (await (await page.request.get(
      `/api/jobs/${job.id}/applications`)).json()) as AppSummary[];
    const scheduled = apps.find((a) => a.stage === "scheduled");
    if (scheduled) return { jobId: job.id, appId: scheduled.id };
  }
  return null;
}

test.describe("interview kit", () => {
  test("generate, answer, submit — candidate becomes interviewed", async ({ page }) => {
    const found = await findScheduledApplication(page);
    test.skip(found === null, "no scheduled application in local DB");
    await page.goto(`/applications/${found!.appId}`);

    // The kit may already be generating from the stage transition; if there is
    // nothing at all, ask for one.
    const generate = page.getByRole("button", { name: /generate interview kit/i });
    if (await generate.isVisible().catch(() => false)) await generate.click();

    const firstAnswer = page.getByPlaceholder(/what they said/i).first();
    await expect(firstAnswer).toBeVisible({ timeout: 60_000 });
    await firstAnswer.fill("Ran the platform for two years.");

    page.once("dialog", (d) => d.accept());
    await page.getByRole("button", { name: /submit interview/i }).click();

    await expect
      .poll(async () => {
        const app = await (await page.request.get(
          `/api/applications/${found!.appId}`)).json();
        return app.stage;
      }, { timeout: 30_000 })
      .toBe("interviewed");
  });
});
