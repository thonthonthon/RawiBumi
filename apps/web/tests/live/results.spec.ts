import { expect, test } from "@playwright/test";

// F7 against the real engine: the results and export views are lazy chunks; they load in the
// HTTP build, say plainly when there is no run, and never show demo data.

const API = process.env.RAWIBUMI_API ?? "http://127.0.0.1:8000";

test("results and report views load against the engine and say when there is no run yet", async ({ page, request }) => {
  const health = await request.get(`${API}/api/health`).catch(() => null);
  test.skip(!health?.ok(), `Engine API not reachable at ${API}`);
  const name = `F7 live ${Date.now()}`;
  const created = await request.post(`${API}/api/projects`, {
    data: { name, latitude_deg: -6.9, longitude_deg: 107.6, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" }
  });
  expect(created.ok()).toBe(true);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/");
  await page.getByText(name).first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+0");
  await expect(page.getByRole("heading", { name: "No results yet" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Demo data")).toHaveCount(0);
  await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
  await expect(page.getByText("Run a simulation first: the report is built from a run's results.")).toBeVisible({ timeout: 15_000 });
  expect(errors).toEqual([]);
});

test("site address against the engine: looked up for the project's own coordinates (lookup stubbed), kept in the browser", async ({ page, request }) => {
  const health = await request.get(`${API}/api/health`).catch(() => null);
  test.skip(!health?.ok(), `Engine API not reachable at ${API}`);
  const name = `F7.1 live ${Date.now()}`;
  const created = await request.post(`${API}/api/projects`, {
    data: { name, latitude_deg: -6.914744, longitude_deg: 107.60981, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" }
  });
  expect(created.ok()).toBe(true);
  const asked: string[] = [];
  await page.route("https://nominatim.openstreetmap.org/reverse**", (route) => {
    asked.push(route.request().url());
    return route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify({ address: { city: "Kota Bandung", state: "Jawa Barat", country: "Indonesia" } }) });
  });
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByText(name).first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+1");
  await expect(page.locator("[data-site-address]")).toHaveValue("Kota Bandung, Jawa Barat, Indonesia", { timeout: 15_000 });
  expect(asked[0]).toContain("lat=-6.914744&lon=107.609810");
  expect(errors).toEqual([]);
});
