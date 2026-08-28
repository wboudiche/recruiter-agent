import { expect, test } from "@playwright/test";
import { login } from "./helpers/login";

interface CriteriaItem {
  name: string;
  weight: number;
  description: string;
}
interface JobSummary {
  id: number;
  criteria: CriteriaItem[];
}
interface AppSummary {
  id: number;
  score: number | null;
  score_rationale: string | null;
}

// Picks any job that already has both criteria and a scored application;
// skips if neither exists locally yet.
async function findScoredApplicationWithCriteria(
  page: import("@playwright/test").Page,
): Promise<
  | { jobId: number; originalCriteria: CriteriaItem[]; appId: number; originalRationale: string | null }
  | null
> {
  const jobsResp = await page.request.get("/api/jobs");
  if (!jobsResp.ok()) return null;
  const jobs = (await jobsResp.json()) as JobSummary[];
  for (const job of jobs) {
    if (!job.criteria || job.criteria.length === 0) continue;
    const appsResp = await page.request.get(`/api/jobs/${job.id}/applications`);
    if (!appsResp.ok()) continue;
    const apps = (await appsResp.json()) as AppSummary[];
    const scored = apps.find((a) => a.score !== null);
    if (scored) {
      return {
        jobId: job.id,
        originalCriteria: job.criteria,
        appId: scored.id,
        originalRationale: scored.score_rationale,
      };
    }
  }
  return null;
}

test.describe("editing criteria rescores existing applicants", () => {
  // Mirrors edit-candidate.spec.ts's restore pattern: criteria is freely
  // reversible data, so mutating an existing job's criteria is safe as
  // long as the original is written back afterward.
  let restore: { jobId: number; criteria: CriteriaItem[] } | null = null;

  test.afterEach(async ({ page }) => {
    if (restore === null) return;
    const { jobId, criteria } = restore;
    restore = null;
    const resp = await page.request.patch(`/api/jobs/${jobId}`, { data: { criteria } });
    expect(
      resp.ok(),
      `restore PATCH /api/jobs/${jobId} failed with ${resp.status()}`,
    ).toBeTruthy();
  });

  test("changing a criterion's description rescores the applicant", async ({ page }) => {
    // One real LLM rescore call plus UI interaction can run past the
    // default 30s test budget.
    test.setTimeout(60_000);

    await login(page);
    const found = await findScoredApplicationWithCriteria(page);
    test.skip(
      found === null,
      "no job with both criteria and a scored application in local DB",
    );
    const { jobId, originalCriteria, appId, originalRationale } = found!;
    restore = { jobId, criteria: originalCriteria };

    await page.goto(`/jobs/${jobId}`);
    await page.getByRole("button", { name: /criteria/i }).first().click();

    const description = page.locator("#desc-0");
    await expect(description).toBeVisible();
    await description.fill(
      `(e2e ${Date.now()}) Weigh prior leadership experience heavily above all else.`,
    );
    await page.getByRole("button", { name: "Save", exact: true }).click();

    // Assert on the rationale text rather than the numeric score: a
    // coincidentally identical score wouldn't prove a rescore actually
    // ran, but a byte-identical rationale from a fresh LLM call
    // essentially never happens.
    await expect(async () => {
      const r = await page.request.get(`/api/applications/${appId}`);
      expect(r.ok()).toBeTruthy();
      const body = await r.json();
      expect(body.score_rationale).not.toBe(originalRationale);
    }).toPass({ timeout: 30_000 });
  });
});
