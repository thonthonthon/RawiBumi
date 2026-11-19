import { Buffer } from "node:buffer";
import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";

// Existing demo shell, real export HTTP client, bounded synthetic route fixtures.
const schema = {
  project_id: "demo-project", run_id: "synthetic-run", format: "csv", resolution: "hourly", level: "project",
  row_count: 2, timestamp_convention: "interval_start", timezone: "Asia/Jakarta", interval_seconds: 3600,
  columns: [
    { id: "timestamp", label: "Interval start", unit: "ISO 8601", required: true },
    { id: "interval_seconds", label: "Interval duration", unit: "s", required: true },
    { id: "ghi_w_m2", label: "Global horizontal irradiance", unit: "W/m²", required: false },
    { id: "pcc_power_w", label: "PCC power (net inverter AC boundary)", unit: "W", required: false },
  ]
};

// Minimal ZIP_STORED writer using Node built-ins only. The browser test asserts
// the saved bytes, leaving scientific CSV/manifest validation to Python tests.
function fixtureZip(): Buffer {
  const entries = [
    ["timeseries.csv", "timestamp,interval_seconds,pcc_power_w\n2026-10-01T10:00:00+07:00,3600,12.5\n2026-10-01T11:00:00+07:00,3600,0\n"],
    ["export-manifest.json", JSON.stringify({ project_id: "demo-project", row_count: 2 })]
  ];
  const local: Buffer[] = [], central: Buffer[] = [];
  let offset = 0;
  for (const [name, content] of entries) {
    const filename = Buffer.from(name), data = Buffer.from(content);
    let crc = 0xffffffff;
    for (const byte of data) {
      crc ^= byte;
      for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
    }
    crc = (crc ^ 0xffffffff) >>> 0;
    const header = Buffer.alloc(30);
    header.writeUInt32LE(0x04034b50, 0); header.writeUInt16LE(20, 4); header.writeUInt16LE(33, 12);
    header.writeUInt32LE(crc, 14); header.writeUInt32LE(data.length, 18); header.writeUInt32LE(data.length, 22); header.writeUInt16LE(filename.length, 26);
    local.push(header, filename, data);
    const directory = Buffer.alloc(46);
    directory.writeUInt32LE(0x02014b50, 0); directory.writeUInt16LE(20, 4); directory.writeUInt16LE(20, 6); directory.writeUInt16LE(33, 14);
    directory.writeUInt32LE(crc, 16); directory.writeUInt32LE(data.length, 20); directory.writeUInt32LE(data.length, 24); directory.writeUInt16LE(filename.length, 28); directory.writeUInt32LE(offset, 42);
    central.push(directory, filename);
    offset += header.length + filename.length + data.length;
  }
  const index = Buffer.concat(central), end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(index.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...local, index, end]);
}

async function open(page: Page, noRuns = false) {
  await page.addInitScript(() => window.localStorage.setItem("rawibumi.language", "en"));
  await page.route("https://nominatim.openstreetmap.org/**", (route) => route.abort());
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  if (noRuns) {
    await page.evaluate(async () => {
      const { uiStore } = await import("/src/state/store.tsx");
      const current = uiStore.getState();
      uiStore.setState({ ...current, state: { ...current.state,
        view: { ...current.state.view, bundle: { ...current.state.view.bundle, simulation_runs: [] } }
      } });
    });
  }
  await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
}

test("loads verified fields, sends selected IDs and saves the exact ZIP bytes", async ({ page }) => {
  let releaseSchema!: () => void;
  const heldSchema = new Promise<void>((resolve) => { releaseSchema = resolve; });
  await page.route("**/api/projects/*/runs/*/exports/schema", async (route) => {
    await heldSchema;
    await route.fulfill({ json: schema });
  });
  let releaseDownload!: () => void;
  const heldDownload = new Promise<void>((resolve) => { releaseDownload = resolve; });
  const bytes = fixtureZip();
  await page.route("**/api/projects/*/runs/*/exports", async (route) => {
    expect(route.request().method()).toBe("POST");
    expect(route.request().postDataJSON()).toEqual({ format: "csv", resolution: "hourly", level: "project", columns: ["pcc_power_w"], formats: ["csv"], deliverable: true });
    await heldDownload;
    await route.fulfill({ contentType: "application/zip", body: bytes });
  });
  await open(page);
  await expect(page.getByText("Loading verified export fields…", { exact: true })).toBeVisible();
  releaseSchema();
  const panel = page.locator("[data-csv-export]");
  await expect(panel).toContainText("2 stored rows");
  await expect(panel.locator("fieldset").first().getByRole("checkbox")).toHaveCount(4);
  await expect(panel.getByRole("checkbox", { name: /^Interval start/ })).toBeDisabled();
  await expect(panel.getByRole("checkbox", { name: /^Interval duration/ })).toBeChecked();
  await panel.getByRole("checkbox", { name: /^Global horizontal/ }).uncheck();
  const downloadEvent = page.waitForEvent("download");
  await panel.getByRole("button", { name: "Download CSV ZIP", exact: true }).click();
  await expect(panel.getByRole("button", { name: "Preparing CSV ZIP…", exact: true })).toBeDisabled();
  await expect(panel.getByRole("checkbox", { name: /^PCC power/ })).toBeDisabled();
  releaseDownload();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe("RawiBumi_results_bundle.zip");
  const path = await download.path();
  expect(path).not.toBeNull();
  expect(await readFile(path!)).toEqual(bytes);
  await expect(panel.getByRole("status")).toHaveText("CSV ZIP download started.");
  await expect(panel.getByRole("button", { name: "Download CSV ZIP", exact: true })).toBeEnabled();
  await panel.getByRole("checkbox", { name: /^PCC power/ }).uncheck();
  await expect(panel.getByRole("button", { name: "Download CSV ZIP", exact: true })).toBeDisabled();
  await expect(panel.getByRole("status")).toHaveCount(0);
});

test("schema failure offers retry; export failure keeps a useful message and allows retry", async ({ page }) => {
  let allowSchema = false;
  let downloads = 0;
  await page.route("**/api/projects/*/runs/*/exports/schema", (route) =>
    allowSchema
      ? route.fulfill({ json: schema })
      : route.fulfill({ status: 422, json: { detail: "Stored dataset is unavailable" } })
  );
  await page.route("**/api/projects/*/runs/*/exports", (route) => {
    downloads++;
    return route.fulfill({ status: 422, json: { detail: "run package artifact hash mismatch" } });
  });
  await open(page);
  await expect(page.getByRole("alert")).toContainText("Stored dataset is unavailable");
  await expect(page.locator("[data-csv-export]")).toHaveCount(0);
  allowSchema = true;
  await page.getByRole("button", { name: "Retry export fields" }).click();
  const panel = page.locator("[data-csv-export]");
  await panel.getByRole("button", { name: "Download CSV ZIP", exact: true }).click();
  await expect(panel.getByRole("alert")).toContainText("CSV download failed. run package artifact hash mismatch");
  await expect(panel.getByRole("button", { name: "Download CSV ZIP", exact: true })).toBeEnabled();
  await panel.getByRole("button", { name: "Download CSV ZIP", exact: true }).click();
  await expect.poll(() => downloads).toBe(2);
});

test("empty schema offers no download or invented fields", async ({ page }) => {
  await page.route("**/api/projects/*/runs/*/exports/schema", (route) => route.fulfill({ json: { ...schema, row_count: 0, columns: [] } }));
  await open(page);
  await expect(page.getByText("This run has no available numerical export fields.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Download CSV ZIP", exact: true })).toHaveCount(0);
});

test("no completed run gives an empty state without fetching export fields", async ({ page }) => {
  let requests = 0;
  await page.route("**/api/projects/*/runs/*/exports/schema", (route) => { requests++; return route.fulfill({ json: schema }); });
  await open(page, true);
  await expect(page.getByText("Complete a simulation before exporting numerical results.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Download CSV ZIP", exact: true })).toHaveCount(0);
  expect(requests).toBe(0);
});

test("existing entitlement denies numerical export in the UI", async ({ page }) => {
  await page.route("**/api/projects/*/runs/*/exports/schema", (route) => route.fulfill({ json: schema }));
  await open(page);
  await page.keyboard.press("Alt+0");
  await page.evaluate(async () => {
    const { setEntitlementSource } = await import("/src/platform/entitlements.ts");
    setEntitlementSource((feature: string) => feature !== "core.export.csv-basic");
  });
  await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
  await expect(page.getByText("Numerical CSV export is unavailable for your current entitlement.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Download CSV ZIP", exact: true })).toHaveCount(0);
});

test("Indonesian export messages and known units are shown", async ({ page }) => {
  await page.route("**/api/projects/*/runs/*/exports/schema", (route) => route.fulfill({ json: schema }));
  await open(page);
  await page.evaluate(async () => {
    const { setLanguage } = await import("/src/i18n/index.ts");
    setLanguage("id");
  });
  const panel = page.locator("[data-csv-export]");
  await expect(panel.getByRole("button", { name: "Unduh ZIP CSV", exact: true })).toBeVisible();
  await expect(panel.getByRole("checkbox", { name: /^Iradiasi global horizontal/ })).toBeVisible();
  await expect(panel).toContainText("W/m²");
  await expect(panel).toContainText("2 baris tersimpan");
});
