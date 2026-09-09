import { expect, test, type Page } from "@playwright/test";

/** Search runs against whatever provider Settings points at. With the
 *  self-hosted SearXNG default that means live public engines, which
 *  rate-limit and CAPTCHA the instance unpredictably — a spec that insists on
 *  result cards is green or red depending on what Google felt like doing that
 *  minute.
 *
 *  So these assert the disjunction the UI actually guarantees: a search either
 *  renders results or explains why it could not. Both are correct outcomes;
 *  what would be a real bug is a third state — the silent "No results found"
 *  that hid a fully blocked instance until the provider learned to report
 *  `unresponsive_engines`. */
async function findAnyJobId(page: Page): Promise<number | null> {
  const resp = await page.request.get("/api/jobs");
  if (!resp.ok()) return null;
  const jobs = (await resp.json()) as { id: number }[];
  return jobs[0]?.id ?? null;
}

async function openSearchTab(page: Page, jobId: number): Promise<void> {
  await page.goto(`/jobs/${jobId}`);
  await page.getByRole("button", { name: "Add candidate" }).click();
  await page.getByRole("tab", { name: "Search" }).click();
}

test.describe("Add candidate → Search", () => {
  test("Search is disabled until both a source and a query are present", async ({ page }) => {
    const jobId = await findAnyJobId(page);
    test.skip(jobId === null, "no job in local DB");
    await openSearchTab(page, jobId!);

    const searchBtn = page
      .getByRole("tabpanel")
      .getByRole("button", { name: "Search", exact: true });
    const queryInput = page.getByPlaceholder("senior Rust engineer Berlin");

    await expect(searchBtn).toBeDisabled();

    // A query with no source selected is still not enough.
    await queryInput.fill("devops kubernetes");
    await expect(searchBtn).toBeDisabled();

    // ...and a source with no query is not either.
    await queryInput.fill("");
    await page.getByRole("button", { name: "GitHub", exact: true }).click();
    await expect(searchBtn).toBeDisabled();

    await queryInput.fill("devops kubernetes");
    await expect(searchBtn).toBeEnabled();
  });

  test("a GitHub search returns result cards, or says why it could not", async ({ page }) => {
    const jobId = await findAnyJobId(page);
    test.skip(jobId === null, "no job in local DB");
    await openSearchTab(page, jobId!);

    await page.getByRole("button", { name: "GitHub", exact: true }).click();
    await page
      .getByPlaceholder("senior Rust engineer Berlin")
      .fill("devops kubernetes location:Tunisia");

    const panel = page.getByRole("tabpanel");
    const responsePromise = page.waitForResponse(
      (r) => r.url().includes("/api/sourcing/search") && r.request().method() === "POST",
    );
    await panel.getByRole("button", { name: "Search", exact: true }).click();
    const body = await (await responsePromise).json();

    const cards = panel.getByRole("link", { name: /github\.com/ });
    const errorBanner = panel.getByText(/^GITHUB:/);

    if (body.results.length > 0) {
      await expect(cards.first()).toBeVisible();
      // Every card offers the action that makes the search useful.
      await expect(
        panel.getByRole("button", { name: "Add", exact: true }).first(),
      ).toBeVisible();
    } else {
      // The failure path must name the source and give a reason — never the
      // bare "No results found" that made a blocked provider look like an
      // empty query.
      await expect(errorBanner).toBeVisible();
      await expect(errorBanner).not.toHaveText(/^GITHUB:\s*$/);
    }
  });

  test("an unreachable provider surfaces a reason, not a bare empty state", async ({ page }) => {
    const jobId = await findAnyJobId(page);
    test.skip(jobId === null, "no job in local DB");
    await openSearchTab(page, jobId!);

    // Force the failure path deterministically rather than waiting for a real
    // engine to block us: the response shape is the contract the UI renders.
    await page.route("**/api/sourcing/search", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          results: [],
          errors: [
            {
              source: "linkedin",
              reason:
                "every search engine is currently blocking this SearXNG instance — brave (too many requests)",
              transient: true,
            },
          ],
        }),
      }),
    );

    await page.getByRole("button", { name: "LinkedIn", exact: true }).click();
    await page.getByPlaceholder("senior Rust engineer Berlin").fill("devops");
    const panel = page.getByRole("tabpanel");
    await panel.getByRole("button", { name: "Search", exact: true }).click();

    await expect(panel.getByText(/blocking this SearXNG instance/i)).toBeVisible();
    await expect(panel.getByText("No results found across selected sources.")).toBeHidden();
  });
});
