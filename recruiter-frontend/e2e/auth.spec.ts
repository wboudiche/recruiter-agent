import { expect, test } from "@playwright/test";
import { DEFAULT_EMAIL, DEFAULT_PASSWORD, login } from "./helpers/login";

test.describe("auth", () => {
  test("default account logs in and lands on /jobs", async ({ page }) => {
    await login(page);
    await expect(page).toHaveURL(/\/jobs/);
    await expect(
      page.getByRole("button", { name: DEFAULT_EMAIL }),
    ).toBeVisible();
  });

  test("wrong password shows credential error and stays on /login", async ({ page }) => {
    await page.goto("/login");
    await page.getByRole("textbox", { name: "Email" }).fill(DEFAULT_EMAIL);
    await page.getByRole("textbox", { name: "Password" }).fill(`${DEFAULT_PASSWORD}-WRONG`);
    await page.getByRole("button", { name: /sign in/i }).click();
    // Reuse the page's own error text. The endpoint returns 401; the
    // form surfaces it inline so we assert on URL + the error copy.
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByText(/credentials/i)).toBeVisible();
  });
});
