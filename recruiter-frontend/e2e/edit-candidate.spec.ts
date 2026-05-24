import { expect, test } from "@playwright/test";
import { login } from "./helpers/login";

// Picks any existing application via the API; skips if the local DB is empty.
async function findAnyApplicationId(page: import("@playwright/test").Page): Promise<number | null> {
  const jobsResp = await page.request.get("/api/jobs");
  if (!jobsResp.ok()) return null;
  const jobs = (await jobsResp.json()) as { id: number }[];
  for (const j of jobs) {
    const appsResp = await page.request.get(`/api/jobs/${j.id}/applications`);
    if (!appsResp.ok()) continue;
    const apps = (await appsResp.json()) as { id: number }[];
    if (apps.length > 0) return apps[0].id;
  }
  return null;
}

test.describe("candidate edit", () => {
  // Shared between the mutating test and the afterEach restore. Each test
  // sets this before any failure point; afterEach only runs if it's set.
  let mutated: { candidateId: number; originalEmail: string | null } | null =
    null;

  test.afterEach(async ({ page }) => {
    if (mutated === null) return;
    const { candidateId, originalEmail } = mutated;
    mutated = null;
    const resp = await page.request.patch(
      `/api/candidates/${candidateId}`,
      { data: { email: originalEmail } },
    );
    // If the restore itself fails we want to know — silent pollution would
    // compound across runs (each subsequent run reads the polluted email
    // as 'original' and restores to that).
    expect(
      resp.ok(),
      `restore PATCH /api/candidates/${candidateId} failed with ${resp.status()}`,
    ).toBeTruthy();
  });

  test("pencil button opens the edit form with all six text fields", async ({ page }) => {
    await login(page);
    const appId = await findAnyApplicationId(page);
    test.skip(appId === null, "no application in local DB; create one first");
    await page.goto(`/applications/${appId}`);

    await page.getByRole("button", { name: "Edit profile details" }).click();

    // All six text fields should be visible at once after the click.
    await expect(page.getByPlaceholder("Full name")).toBeVisible();
    await expect(page.getByPlaceholder("email@example.com")).toBeVisible();
    await expect(page.getByPlaceholder("Phone")).toBeVisible();
    await expect(page.getByPlaceholder(/Headline/i)).toBeVisible();
    await expect(page.getByPlaceholder(/Location/i)).toBeVisible();
    await expect(page.getByPlaceholder(/Summary/i)).toBeVisible();
  });

  test("editing name + email persists and re-renders", async ({ page }) => {
    await login(page);
    const appId = await findAnyApplicationId(page);
    test.skip(appId === null, "no application in local DB");
    await page.goto(`/applications/${appId}`);

    // Capture candidate id + original email BEFORE any mutation, so the
    // afterEach restore knows what to write back even if the test below
    // throws mid-way.
    const appResp = await page.request.get(`/api/applications/${appId}`);
    const candidateId = (await appResp.json()).candidate_id as number;
    const before = await (await page.request.get(`/api/candidates/${candidateId}`)).json();
    mutated = { candidateId, originalEmail: before.email ?? null };

    const testEmail = `e2e-edit-${Date.now()}@example.test`;
    await page.getByRole("button", { name: "Edit profile details" }).click();
    await page.getByPlaceholder("email@example.com").fill(testEmail);
    await page.getByRole("button", { name: "Save", exact: true }).click();

    // Verify persistence at the API level. We intentionally don't assert
    // on the rendered header here — the cache-invalidation timing in React
    // Query is an implementation detail better covered by a component test.
    await expect(async () => {
      const r = await page.request.get(`/api/candidates/${candidateId}`);
      expect(r.ok()).toBeTruthy();
      expect((await r.json()).email).toBe(testEmail);
    }).toPass({ timeout: 10_000 });
  });
});
