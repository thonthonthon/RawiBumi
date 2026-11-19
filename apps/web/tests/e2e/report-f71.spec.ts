import { expect, test, type Page } from "@playwright/test";

// F7.1 (owner's directions, 22 Oct): the report cover shows the project identity with an address
// looked up from the coordinates and editable by the user; a linked table of contents; one
// mapping table per inverter with azimuth and tilt; a sun-path and shading chapter.
// The lookup service is stubbed here: tests never call the real Nominatim.

const NOMINATIM = "https://nominatim.openstreetmap.org/reverse**";
const reply = {
  display_name: "Jalan Contoh, Kelurahan A, Kecamatan B, Kota C, DKI Jakarta, 10110, Indonesia",
  address: { road: "Jalan Contoh", village: "Kelurahan A", city_district: "Kecamatan B", city: "Kota C", state: "DKI Jakarta", postcode: "10110", country: "Indonesia" }
};

async function open(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.evaluate(() => window.localStorage.clear());
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  return errors;
}

test("address: looked up once from the coordinates, edited by the user, shown on the report cover", async ({ page }) => {
  const asked: string[] = [];
  await page.route(NOMINATIM, (route) => {
    asked.push(route.request().url());
    return route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(reply) });
  });
  const errors = await open(page);
  await page.keyboard.press("Alt+1");
  const field = page.locator("[data-site-address]");
  await expect(field).toHaveValue("Jalan Contoh, Kelurahan A, Kecamatan B, Kota C, DKI Jakarta, 10110, Indonesia");
  await expect(page.locator('[data-address-status="idle"]')).toContainText("OpenStreetMap Nominatim");
  await expect(page.locator('[data-address-status="idle"]')).toContainText("© OpenStreetMap contributors");
  // One request only, also after the 1.1 s spacing a second (throttled) request would wait for.
  await page.waitForTimeout(1500);
  expect(asked).toHaveLength(1);
  expect(asked[0]).toContain("lat=-6.200000&lon=106.820000");

  await field.fill("Jl. Gudang 7, Jakarta Utara");
  await expect(page.getByText("Edited by you.")).toBeVisible();

  await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
  await expect(page.locator("[data-report-address]")).toContainText("Jl. Gudang 7, Jakarta Utara");
  await page.getByRole("button", { name: "Preview report" }).click();
  const frame = page.frameLocator('iframe[title="Report preview"]');
  const cover = frame.locator("[data-cover]");
  await expect(cover.locator("h1")).toHaveText("Warehouse rooftop (demo)");
  await expect(cover.locator("[data-address] td")).toHaveText("Jl. Gudang 7, Jakarta Utara");
  await expect(cover).toContainText("6.20000° S, 106.82000° E");
  await expect(cover).toContainText("Address data © OpenStreetMap contributors.");
  // No engineering revision data on the cover.
  await expect(cover).not.toContainText("Run");
  await expect(cover).not.toContainText("fingerprint");
  // The edit survives a reload and is not replaced by a new lookup.
  await page.reload();
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+1");
  await expect(page.locator("[data-site-address]")).toHaveValue("Jl. Gudang 7, Jakarta Utara");
  expect(asked).toHaveLength(1);
  expect(errors).toEqual([]);
});

test("report: linked contents, one mapping table per inverter with azimuth and tilt, shading chapter", async ({ page }) => {
  await page.route(NOMINATIM, (route) => route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(reply) }));
  const errors = await open(page);
  await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
  await page.getByRole("button", { name: "Preview report" }).click();
  const frame = page.frameLocator('iframe[title="Report preview"]');
  const toc = frame.locator("[data-toc] a");
  await expect(toc).toHaveCount(12);
  await expect(toc.nth(2)).toHaveAttribute("href", "#ch-topology");
  await expect(toc.nth(2)).toContainText("Inverter, MPPT and string mapping");

  const inv = frame.locator('[data-inverter="INV-01"]');
  await expect(inv.locator("h3")).toContainText("INV-01 ·");
  await expect(inv).toContainText("DC capacity 41.8 kWp");
  await expect(inv.locator("tbody tr")).toHaveCount(5);
  const first = inv.locator("tbody tr").first().locator("td");
  await expect(first).toHaveText(["1", "S1", "16", "Roof A array", "0°", "10°", "Portrait"]);
  await expect(frame.locator("#ch-topology")).toContainText("Azimuth: 0° = north, clockwise");

  const shading = frame.locator("#ch-shading");
  await expect(shading.locator('[data-shading="not-quantified"]')).toBeVisible();
  await expect(shading.locator('[data-sunpath="pending"]')).toContainText("proposal 0005, item E9");
  // Run ID once, in Methodology.
  await expect(frame.locator("#ch-method code").first()).toHaveText(/^run-/);
  expect(errors).toEqual([]);
});

test("address: lookup offline fails plainly; the report still builds and says no address is given", async ({ page }) => {
  await page.route(NOMINATIM, (route) => route.abort("internetdisconnected"));
  const errors = await open(page);
  await page.keyboard.press("Alt+1");
  await expect(page.locator('[data-address-status="failed"]')).toContainText("Address lookup failed");
  await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
  await page.getByRole("button", { name: "Preview report" }).click();
  const frame = page.frameLocator('iframe[title="Report preview"]');
  await expect(frame.locator("[data-cover] [data-address] td")).toHaveText("Not given");
  await expect(frame.locator("[data-cover]")).not.toContainText("Address data");
  expect(errors).toEqual([]);
});

test("address: switched off by the user, no request is sent", async ({ page }) => {
  let asked = 0;
  await page.route(NOMINATIM, (route) => {
    asked++;
    return route.abort();
  });
  await page.addInitScript(() => window.localStorage.setItem("rawibumi.addressLookup", "off"));
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+1");
  await expect(page.getByLabel("Look up the address online")).not.toBeChecked();
  await page.waitForTimeout(500);
  expect(asked).toBe(0);
});
