import { expect, test } from "@playwright/test";
import { login } from "./helpers/login";

type PageT = import("@playwright/test").Page;

async function pollStage(
  page: PageT,
  appId: number,
  expected: string,
  timeoutMs = 20_000,
): Promise<void> {
  await expect(async () => {
    const r = await page.request.get(`/api/applications/${appId}`);
    expect(r.ok()).toBeTruthy();
    const body = await r.json();
    expect(body.stage).toBe(expected);
  }).toPass({ timeout: timeoutMs });
}

test.describe("post-invite pipeline stages", () => {
  // There's no DELETE endpoint for jobs/applications, so this test's
  // fixture job is left behind — same as any job a recruiter creates by
  // hand. Named distinctly so it reads as e2e fixture data in the board.
  test("invited candidate advances scheduled → interviewed → offer → hired", async ({
    page,
  }) => {
    // Two real LLM calls (extract + score) plus a real SMTP send and
    // four UI-driven stage transitions can run well past the default
    // 30s test budget.
    test.setTimeout(120_000);

    await login(page);

    const settingsResp = await page.request.get("/api/settings");
    expect(settingsResp.ok()).toBeTruthy();
    const settings = (await settingsResp.json()) as { has_smtp_config: boolean };
    test.skip(
      !settings.has_smtp_config,
      "SMTP is not configured locally; Notify & invite can't run",
    );

    const jobResp = await page.request.post("/api/jobs", {
      data: {
        title: `E2E — post-invite stages ${Date.now()}`,
        description: "Backend engineer, 5+ years, Rust preferred.",
        criteria: [{ name: "Rust", weight: 1.0, description: "Rust experience" }],
      },
    });
    expect(jobResp.ok()).toBeTruthy();
    const jobId = (await jobResp.json()).id as number;

    const candResp = await page.request.post(`/api/jobs/${jobId}/candidates`, {
      data: {
        kind: "paste",
        content:
          "Jordan Rivers\nSenior Backend Engineer, 6 years of Rust.\n" +
          `Email: e2e-notify-${Date.now()}@example.test`,
      },
    });
    expect(candResp.ok()).toBeTruthy();
    const appId = (await candResp.json()).application_id as number;

    await pollStage(page, appId, "scored", 45_000);

    const validateResp = await page.request.patch(`/api/applications/${appId}`, {
      data: { stage: "validated" },
    });
    expect(validateResp.ok()).toBeTruthy();

    const slotStart = new Date(Date.now() + 24 * 3600_000);
    const slotEnd = new Date(slotStart.getTime() + 3600_000);
    const notifyResp = await page.request.post(`/api/applications/${appId}/notify`, {
      data: {
        channel: "smtp",
        subject: "Interview at Acme (e2e)",
        body: "Hi — here are some interview times.",
        slots: [{ start: slotStart.toISOString(), end: slotEnd.toISOString() }],
      },
    });
    expect(
      notifyResp.ok(),
      `POST notify failed with ${notifyResp.status()}: ${await notifyResp.text()}`,
    ).toBeTruthy();
    await pollStage(page, appId, "invited");

    await page.goto(`/applications/${appId}`);

    await page.getByRole("button", { name: /mark as scheduled/i }).click();
    await pollStage(page, appId, "scheduled");

    await page.getByRole("button", { name: /mark as interviewed/i }).click();
    await pollStage(page, appId, "interviewed");

    await page.getByRole("button", { name: /extend offer/i }).click();
    await pollStage(page, appId, "offer");

    await page.getByRole("button", { name: /mark as hired/i }).click();
    await pollStage(page, appId, "hired");

    // Hired is fully terminal: no further forward button, and Reject
    // (previously available at every prior stage) is gone too.
    await expect(
      page.getByRole("button", { name: /mark as hired/i }),
    ).not.toBeVisible();
    await expect(page.getByRole("button", { name: /^reject$/i })).not.toBeVisible();
  });
});
