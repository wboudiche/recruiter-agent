import { defineConfig, devices } from "@playwright/test";

import { STORAGE_STATE } from "./e2e/helpers/storage-state";

// Tests assume the docker compose stack is already running locally.
// Start it with: docker compose up -d
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:8088";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,           // serial keeps DB state predictable
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    // Logs in once and saves the session; everything else reuses it. Without
    // this each spec logs in for itself and the suite trips the login rate
    // limit, failing specs unrelated to auth. See e2e/auth.setup.ts.
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      // auth.spec.ts drives the login form itself (including the wrong-password
      // path), so it needs an unauthenticated context and its own logins.
      name: "auth",
      testMatch: /auth\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "chromium",
      testIgnore: /auth\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], storageState: STORAGE_STATE },
      dependencies: ["setup"],
    },
  ],
});
