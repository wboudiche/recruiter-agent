import { expect, test } from "@playwright/test";
import { login } from "./helpers/login";

async function findAnyJobId(page: import("@playwright/test").Page): Promise<number | null> {
  const resp = await page.request.get("/api/jobs");
  if (!resp.ok()) return null;
  const jobs = (await resp.json()) as { id: number }[];
  return jobs[0]?.id ?? null;
}

test.describe("Add candidate → Search → Suggest from JD", () => {
  test("Suggest button is disabled until a source is picked, then fills the input", async ({
    page,
  }) => {
    await login(page);
    const jobId = await findAnyJobId(page);
    test.skip(jobId === null, "no job in local DB");
    await page.goto(`/jobs/${jobId}`);

    await page.getByRole("button", { name: "Add candidate" }).click();
    await page.getByRole("tab", { name: "Search" }).click();

    // Sparkles button (icon-only) carries the aria-label set by the component.
    const suggestBtn = page.getByRole("button", { name: /suggest query from jd/i });
    await expect(suggestBtn).toBeDisabled();

    // Pick LinkedIn → button enables.
    await page.getByRole("button", { name: "LinkedIn", exact: true }).click();
    await expect(suggestBtn).toBeEnabled();

    // Trigger suggestion. The LLM call may take a few seconds, so be patient.
    const queryInput = page.getByPlaceholder("senior Rust engineer Berlin");
    await expect(queryInput).toHaveValue("");
    await suggestBtn.click();
    await expect(queryInput).not.toHaveValue("", { timeout: 30_000 });
  });
});
