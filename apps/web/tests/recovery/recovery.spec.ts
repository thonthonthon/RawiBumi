import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.beforeEach(async ({ page }) => {
  await page.route("https://nominatim.openstreetmap.org/**", (r) => r.abort());
});

test("engine outage offers retry, distinguishes unavailable from empty and recovers without reload", async ({ page }) => {
  let offline = true;
  await page.route("**/api/**", (r) => r.fulfill(offline
    ? { status: 503, json: { detail: "Engine restarting" } }
    : { json: r.request().url().endsWith("catalog") ? { modules: [], inverters: [] } : [] }));
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("Engine restarting");
  await expect(page.getByText("Projects could not be loaded. Retry the connection above.")).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  offline = false; await page.getByRole("button", { name: "Retry connection" }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Retry connection" })).toHaveCount(0);
  await expect(page.getByText("0 modules and 0 inverters in the library")).toBeVisible();
});

test("creation failure is inline, focused, retryable, and preserves the form with no unhandled rejection", async ({ page }) => {
  const errors: string[] = []; page.on("pageerror", (e) => errors.push(e.message));
  let posts = 0;
  await page.route("**/api/**", async (r) => {
    if (r.request().method() === "POST") {
      posts++;
      await r.fulfill({ status: 422, json: { detail: [{ loc: ["body", "timezone"], msg: "Unknown timezone" }] } });
    } else await r.fulfill({ json: r.request().url().endsWith("catalog") ? { modules: [], inverters: [] } : [] });
  });
  await page.goto("/");
  await page.getByLabel("Project name", { exact: true }).fill("Keep this project name");
  const submit = page.getByRole("button", { name: "Create project", exact: true });
  await submit.click(); await expect(page.getByRole("alert")).toContainText("body.timezone: Unknown timezone");
  await expect(page.getByRole("alert")).toBeFocused();
  await expect(page.getByLabel("Project name", { exact: true })).toHaveValue("Keep this project name");
  await expect(submit).toBeEnabled(); await submit.click();
  await expect.poll(() => posts).toBe(2); expect(errors).toEqual([]);
});

test("project opening failure is announced on the start screen and can be dismissed", async ({ page }) => {
  await page.route("**/api/**", (r) => {
    const url = r.request().url();
    if (url.endsWith("catalog")) return r.fulfill({ json: { modules: [], inverters: [] } });
    if (url.endsWith("/projects")) return r.fulfill({ json: [{ project_id: "missing", name: "Deleted elsewhere", latitude_deg: 0, longitude_deg: 0, timezone: "UTC" }] });
    return r.fulfill({ status: 404, json: { detail: "Project no longer exists. Refresh the project list." } });
  });
  await page.goto("/"); await page.getByRole("button", { name: "Deleted elsewhere" }).click();
  await expect(page.locator(".toasts")).toContainText("Project no longer exists");
  await expect(page.locator(".start")).toBeVisible();
  await page.getByRole("button", { name: "Dismiss notification" }).click();
  await expect(page.locator(".toast")).toHaveCount(0);
});
