import { test as setup } from "@playwright/test";
import { login } from "./helpers/login";
import { STORAGE_STATE } from "./helpers/storage-state";

/** Authenticate once for the whole suite.
 *
 *  Playwright gives every test a fresh browser context, so without a shared
 *  session each spec has to log in for itself. That put the suite at nine
 *  logins in about forty seconds against `POST /api/auth/login/password`,
 *  which is deliberately rate-limited — so specs with nothing to do with auth
 *  failed on 429s depending on where they landed in the run order.
 *
 *  One login here, saved as storage state and reused by every spec, takes that
 *  back to one. `auth.spec.ts` opts out (it tests the login form itself, wrong
 *  password included) and keeps its own real logins. */
setup("authenticate once for the suite", async ({ page }) => {
  await login(page);
  await page.context().storageState({ path: STORAGE_STATE });
});
