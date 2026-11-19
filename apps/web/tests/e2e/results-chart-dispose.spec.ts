import { expect, test } from "@playwright/test";

test("heatmap disposal leaves no pending paint error at 8x CPU slowdown", async ({ page }, testInfo) => {
  // Measured 8x tab-switch stress plus startup/trace margin; ordinary specs keep their timeout.
  test.setTimeout(90_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const started = Date.now();
  const cdp = await page.context().newCDPSession(page);
  const switches: Array<{ target: string; iteration: number }> = [];
  let stressStarted: number | undefined;
  try {
    await page.goto("/");
    await page.locator(".start__row").first().click();
    await expect(page.locator(".rail")).toBeVisible();
    await page.keyboard.press("Alt+0");
    await expect(page.getByRole("heading", { name: "Results", exact: true })).toBeVisible();
    await expect(page.locator('[data-chart="Monthly energy bar chart"] canvas').first()).toBeVisible();
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 8 });
    stressStarted = Date.now();
    const targets = [
      ["Daily profile", "Average daily power profile"],
      ["Loss waterfall", "Loss waterfall from reference energy to AC energy"],
      ["Monthly", "Monthly energy bar chart"]
    ] as const;
    for (const [target, label] of targets) {
      for (let iteration = 0; iteration < 5; iteration++) {
        await page.getByRole("radio", { name: "Heatmap", exact: true }).click();
        await expect(page.locator('[data-chart="Heatmap of mean power by week and hour"] canvas').first()).toBeVisible();
        await page.getByRole("radio", { name: target, exact: true }).click();
        await expect(page.locator(`[data-chart="${label}"] canvas`).first()).toBeVisible();
        switches.push({ target, iteration });
      }
    }
    // Allow any queued multi-frame paint continuation to execute before checking.
    await page.waitForTimeout(500);
    expect(switches).toHaveLength(15);
    expect(errors).toEqual([]);
  } finally {
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 1 });
    await cdp.detach();
    await testInfo.attach("chart-dispose-stress", {
      contentType: "application/json",
      body: JSON.stringify({ cpu_throttle: 8, duration_ms: Date.now() - started,
        stress_duration_ms: stressStarted === undefined ? null : Date.now() - stressStarted, switches, errors }, null, 2)
    });
  }
});
