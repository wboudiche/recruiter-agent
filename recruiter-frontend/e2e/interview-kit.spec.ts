import { expect, test, type Page } from "@playwright/test";

/** Poll a stage via the API — the same shape used by
 *  post-invite-stages.spec.ts, kept here as expect.poll (rather than that
 *  spec's expect(...).toPass) so the final assertion matches what was
 *  reviewed and explicitly asked to stay unchanged. */
async function pollStage(
  page: Page,
  appId: number,
  expected: string,
  timeoutMs = 30_000,
): Promise<void> {
  await expect
    .poll(async () => {
      const app = await (await page.request.get(`/api/applications/${appId}`)).json();
      return app.stage;
    }, { timeout: timeoutMs })
    .toBe(expected);
}

/** `useInterviewKit` (src/hooks/use-interview-kit.ts) sets no
 *  `refetchInterval`, and the app's QueryClient defaults to
 *  `refetchOnWindowFocus: false` (src/App.tsx) — so a page loaded while
 *  generation is still in flight shows "Generating questions…" with nothing
 *  to ever prompt a refetch. Wait for the backend kit to actually finish
 *  before loading the UI, the way a recruiter checking back later would. */
async function waitForKitReady(
  page: Page,
  appId: number,
  timeoutMs = 60_000,
): Promise<void> {
  await expect
    .poll(async () => {
      const resp = await page.request.get(`/api/applications/${appId}/interview-kit`);
      const body = await resp.json();
      return body.kit?.status ?? null;
    }, { timeout: timeoutMs })
    .toBe("ready");
}

test.describe("interview kit", () => {
  // Seeds its own job + candidate and drives it to `scheduled` via the API —
  // the state this feature's flow starts from — instead of hunting for an
  // ambient scheduled candidate. The earlier version searched the DB for
  // whatever happened to be sitting at `scheduled`, drove it to `interviewed`
  // with no way back, and skipped outright whenever nothing was there (which
  // is every ordinary run, since post-invite-stages.spec.ts's fixture sails
  // straight through to `hired`). That mutated data the test didn't own and
  // gave almost no ongoing regression coverage. Seeding removes both
  // problems: this spec always has a candidate, and it only ever touches its
  // own.
  //
  // There's no DELETE endpoint for jobs/applications, so — same as
  // post-invite-stages.spec.ts — this fixture is deliberately left behind
  // rather than cleaned up, same as any job a recruiter creates by hand.
  // Named distinctly so it reads as e2e fixture data in the board.
  test("generate, answer, submit — candidate becomes interviewed", async ({ page }) => {
    // Three real LLM calls (extract + score + kit generation) plus a real
    // SMTP send can run well past the default 30s test budget.
    test.setTimeout(180_000);

    const settingsResp = await page.request.get("/api/settings");
    expect(settingsResp.ok()).toBeTruthy();
    const settings = (await settingsResp.json()) as { has_smtp_config: boolean };
    test.skip(
      !settings.has_smtp_config,
      "SMTP is not configured locally; Notify & invite can't run",
    );

    const jobResp = await page.request.post("/api/jobs", {
      data: {
        title: `E2E — interview kit ${Date.now()}`,
        description: "Backend engineer, 5+ years, DevOps focus.",
        criteria: [{ name: "DevOps", weight: 1.0, description: "DevOps experience" }],
      },
    });
    expect(jobResp.ok()).toBeTruthy();
    const jobId = (await jobResp.json()).id as number;

    const candResp = await page.request.post(`/api/jobs/${jobId}/candidates`, {
      data: {
        kind: "paste",
        content:
          "Taylor Probe\nSenior DevOps Engineer, 6 years running Kubernetes in production.\n" +
          `Email: e2e-interview-kit-${Date.now()}@example.test`,
      },
    });
    expect(candResp.ok()).toBeTruthy();
    const appId = (await candResp.json()).application_id as number;

    await pollStage(page, appId, "scored", 45_000);

    const validateResp = await page.request.patch(`/api/applications/${appId}`, {
      data: { stage: "validated" },
    });
    expect(validateResp.ok()).toBeTruthy();

    // `invited` is only reachable through /notify — the generic PATCH
    // schema rejects it outright (see post-invite-stages.spec.ts).
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

    // Stop the PATCH chain at `scheduled` — that's where this feature's flow
    // starts. Entering it also enqueues kit generation on the backend.
    const scheduleResp = await page.request.patch(`/api/applications/${appId}`, {
      data: { stage: "scheduled" },
    });
    expect(scheduleResp.ok()).toBeTruthy();
    await pollStage(page, appId, "scheduled");

    await waitForKitReady(page, appId);

    // --- UI flow against our own fixture from here on ---

    // Second interviewer: created through the admin users API in this
    // spec's own fixture, assigned alongside the admin running the test.
    const stamp = Date.now();
    const created = await page.request.post("/api/users", {
      data: { email: `e2e-interviewer-${stamp}@example.test`, name: "Second Interviewer",
              role: "viewer", password: "pw-12345678" },
    });
    expect(created.ok()).toBeTruthy();
    const secondId = (await created.json()).id as number;
    const meId = (await (await page.request.get("/api/auth/me")).json()).id as number;
    const assign = await page.request.put(`/api/applications/${appId}/interviewers`, {
      data: { user_ids: [meId, secondId] },
    });
    expect(assign.ok()).toBeTruthy();

    // Admin fills and submits their sheet in the UI.
    await page.goto(`/applications/${appId}?tab=interview`);

    // The kit may already be generating from the stage transition; if there
    // is nothing at all, ask for one.
    const generate = page.getByRole("button", { name: /generate interview kit/i });
    if (await generate.isVisible().catch(() => false)) await generate.click();

    const firstAnswer = page.getByPlaceholder(/what they said/i).first();
    await expect(firstAnswer).toBeVisible({ timeout: 60_000 });
    await firstAnswer.fill("Ran the platform for two years.");
    await page.getByRole("button", { name: /^hire$/i }).click();
    await page.getByRole("button", { name: /submit interview/i }).click();
    const dialog = page.getByRole("dialog");
    if (await dialog.isVisible().catch(() => false)) {
      await dialog.getByRole("button", { name: /submit anyway/i }).click();
    }
    await expect(page.getByText(/interview recorded/i)).toBeVisible();

    // One of two sheets in: still scheduled, and the card says so on the
    // kanban board (the candidate page doesn't render that card).
    await pollStage(page, appId, "scheduled", 5_000);
    await page.goto(`/jobs/${jobId}`);
    await expect(page.getByText("1/2 sheets in")).toBeVisible({ timeout: 10_000 });

    // Second interviewer submits through the API (a separate browser
    // context would be the purist option; the rule under test is the
    // server's, and the API is the same path the UI takes).
    const ctx = await page.context().browser()!.newContext();
    try {
      const other = await ctx.newPage();
      // This is the suite's one deliberate extra real login beyond
      // auth.setup.ts's and auth.spec.ts's: the sheet submit below must be
      // attributed to the second interviewer, and logging in as them is the
      // only way to do that. The login endpoint allows 5 attempts per
      // minute; this test's earlier LLM/SMTP work keeps its one login well
      // clear of the other logins in a serial run.
      await other.goto("/login");
      await other.getByRole("textbox", { name: "Email" }).fill(`e2e-interviewer-${stamp}@example.test`);
      await other.getByRole("textbox", { name: "Password" }).fill("pw-12345678");
      await other.getByRole("button", { name: /sign in/i }).click();
      await expect(other).toHaveURL(/\/jobs/);
      const submit = await other.request.post(`/api/applications/${appId}/interview-kit/sheet/submit`);
      expect(submit.ok(), await submit.text()).toBeTruthy();
    } finally {
      await ctx.close();
    }

    await pollStage(page, appId, "interviewed", 30_000);
  });
});
