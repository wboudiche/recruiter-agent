import { expect, type Page } from "@playwright/test";

// Reads from env so the same suite works against `.env` and CI. Defaults
// match the local dev .env we've been using throughout the session.
export const DEFAULT_EMAIL =
  process.env.E2E_DEFAULT_EMAIL ?? "admin@acme.com";
export const DEFAULT_PASSWORD =
  process.env.E2E_DEFAULT_PASSWORD ?? "admin";

export async function login(
  page: Page,
  email: string = DEFAULT_EMAIL,
  password: string = DEFAULT_PASSWORD,
): Promise<void> {
  await page.goto("/login");
  await page.getByRole("textbox", { name: "Email" }).fill(email);
  await page.getByRole("textbox", { name: "Password" }).fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  // The app redirects to /jobs (or /<next>) after a successful login; wait
  // for the post-login shell to render so subsequent assertions are stable.
  await expect(page).toHaveURL(/\/jobs/);
}
