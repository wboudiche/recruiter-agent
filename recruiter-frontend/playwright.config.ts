import { defineConfig, devices } from "@playwright/test";

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
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
