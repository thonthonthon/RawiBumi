import { Buffer } from "node:buffer";
import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";

// Transport/UI fixtures only. Enabled mocks represent an opted-in Community
// server, not a successful hosted login or proof of production authorization.
const capability = (enabled: boolean) => ({ enabled, format: "pdf", text_based: true, locales: ["en", "id"] });
const schema = {
  project_id: "demo-project", run_id: "synthetic-run", format: "csv", resolution: "hourly", level: "project",
  row_count: 2, timestamp_convention: "interval_start", timezone: "Asia/Jakarta", interval_seconds: 3600,
  columns: [
    { id: "timestamp", label: "Interval start", unit: "ISO 8601", required: true },
    { id: "interval_seconds", label: "Interval duration", unit: "s", required: true },
    { id: "pcc_power_w", label: "PCC power", unit: "W", required: false },
  ]
};

function fixturePDF(): Buffer {
  const stream = "BT /F1 12 Tf 20 60 Td (Synthetic transport fixture) Tj ET\n";
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}endstream`,
  ];
  let document = Buffer.from("%PDF-1.7\n%\x80\xff\x81\xfe\n", "latin1");
  const offsets = [0];
  for (const [index, object] of objects.entries()) {
    offsets.push(document.length);
    document = Buffer.concat([document, Buffer.from(`${index + 1} 0 obj\n${object}\nendobj\n`)]);
  }
  const xref = document.length;
  return Buffer.concat([document, Buffer.from(`xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map((n) => `${String(n).padStart(10, "0")} 00000 n \n`).join("")}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`)]);
}
const bytes = fixturePDF();
const panel = (page: Page) => page.locator("[data-native-pdf-export]");

async function open(page: Page, options: { multiple?: boolean; noCompleted?: boolean; hint?: boolean } = {}) {
  await page.addInitScript(() => window.localStorage.setItem("rawibumi.language", "en"));
  await page.route("https://nominatim.openstreetmap.org/**", (route) => route.abort());
  await page.route("**/api/projects/*/runs/*/exports/schema", (route) => route.fulfill({ json: schema }));
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.evaluate(async ({ multiple, noCompleted, hint }) => {
    const { setEntitlementSource } = await import("/src/platform/entitlements.ts");
    setEntitlementSource(hint === false ? (feature: string) => ![
      "core.export.pdf-native", "electrical.sld-full", "export.csv-string-level", "module.finmod", "report.branded"
    ].includes(feature) : null);
    if (!multiple && !noCompleted) return;
    const { uiStore } = await import("/src/state/store.tsx");
    const current = uiStore.getState();
    const view = current.state.view;
    const template = view.bundle.simulation_runs.at(-1);
    const simulation_runs = noCompleted ? [{ ...template, simulation_run_id: "run-pending", status: "running", summary_result: null }] : [
      { ...template, simulation_run_id: "run-complete-a", status: "completed" },
      { ...template, simulation_run_id: "run-complete-b", status: "completed_with_warnings" },
      { ...template, simulation_run_id: "run-pending", status: "running", summary_result: null },
      { ...template, simulation_run_id: "run-failed", status: "failed", summary_result: null },
    ];
    uiStore.setState({ ...current, state: { ...current.state, view: { ...view, bundle: { ...view.bundle, simulation_runs } } } });
  }, options);
  await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
}

test("disabled server capability blocks native PDF even with every PDF hint allowed", async ({ page }) => {
  let downloads = 0;
  await page.route("**/api/reporting/native-pdf/capability", (route) => route.fulfill({ json: capability(false) }));
  await page.route("**/api/projects/*/runs/*/exports/native-pdf*", (route) => {
    downloads++;
    return route.fulfill({ status: 404, json: { detail: "Native PDF download is unavailable." } });
  });
  await open(page, { hint: true });
  await expect(panel(page)).toContainText("Native PDF download is not enabled on this server.");
  await expect(panel(page).getByRole("button", { name: "Download native PDF", exact: true })).toHaveCount(0);
  await panel(page).getByRole("button", { name: "Recheck PDF availability" }).click();
  await expect(panel(page)).toContainText("Native PDF download is not enabled on this server.");
  expect(downloads).toBe(0);
  // A direct client call also receives server denial; the hint grants nothing.
  const error = await page.evaluate(async () => {
    const { exportAPI } = await import("/src/client.ts");
    try { await exportAPI.nativePDF("demo-project", "synthetic-run", "en"); }
    catch (e) { return (e as Error).message; }
    return "unexpected success";
  });
  expect(error).toBe("Native PDF download is unavailable.");
  expect(downloads).toBe(1);
});

for (const locale of ["en", "id"] as const) {
  test(`enabled Community mock downloads exact bytes in ${locale} for the chosen completed run`, async ({ page }) => {
    await page.route("**/api/reporting/native-pdf/capability", (route) => route.fulfill({ json: capability(true) }));
    const requests: string[] = [];
    await page.route("**/api/projects/*/runs/*/exports/native-pdf*", (route) => {
      expect(route.request().method()).toBe("POST");
      const body = route.request().postDataJSON();
      expect(body.locale).toBe(locale);
      expect(Object.keys(body).sort()).toEqual(["locale", "plan_figure_png"]);
      expect(body.plan_figure_png === null || body.plan_figure_png.startsWith("data:image/png;base64,")).toBe(true);
      requests.push(route.request().url());
      return route.fulfill({ contentType: "application/pdf", body: bytes,
        headers: { "Content-Disposition": 'attachment; filename="ignored-server-name.pdf"' } });
    });
    await open(page, { multiple: true });
    const selector = page.getByRole("combobox", { name: "Numerical export run", exact: true });
    await expect(selector.locator("option")).toHaveCount(2);
    await expect(selector).toHaveValue("run-complete-b");
    await selector.selectOption("run-complete-a");
    if (locale === "id") {
      await page.evaluate(async () => (await import("/src/i18n/index.ts")).setLanguage("id"));
    }
    const button = panel(page).getByRole("button", { name: locale === "en" ? "Download native PDF" : "Unduh PDF native", exact: true });
    await expect(button).toBeEnabled();
    const event = page.waitForEvent("download");
    await button.click();
    const download = await event;
    expect(download.suggestedFilename()).toBe("RawiBumi_verified_report.pdf");
    expect(await readFile((await download.path())!)).toEqual(bytes);
    expect(requests).toHaveLength(1);
    const request = new URL(requests[0]);
    expect(request.pathname).toBe("/api/projects/demo-project/runs/run-complete-a/exports/native-pdf");
    expect([...request.searchParams.entries()]).toEqual([]);
    await expect(panel(page).getByRole("status")).toHaveText(locale === "en" ? "Native PDF download started." : "Unduhan PDF native dimulai.");
    await expect(button).toBeEnabled();
  });
}

test("capability failure stays unavailable and can retry through loading", async ({ page }) => {
  let available = false;
  let release!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/reporting/native-pdf/capability", async (route) => {
    if (!available) return route.fulfill({ status: 503, json: { detail: "Unavailable" } });
    await held;
    await route.fulfill({ json: capability(true) });
  });
  await open(page);
  await expect(panel(page)).toContainText("Native PDF availability could not be checked.");
  await expect(panel(page).getByRole("button", { name: "Download native PDF", exact: true })).toHaveCount(0);
  available = true;
  await panel(page).getByRole("button", { name: "Recheck PDF availability" }).click();
  await expect(panel(page)).toHaveAttribute("aria-busy", "true");
  await expect(panel(page)).toContainText("Checking native PDF availability…");
  release();
  await expect(panel(page).getByRole("button", { name: "Download native PDF", exact: true })).toBeEnabled();
});

test("download failure retries, prevents duplicate in-flight requests and revokes its temporary URL", async ({ page }) => {
  await page.route("**/api/reporting/native-pdf/capability", (route) => route.fulfill({ json: capability(true) }));
  let attempts = 0;
  let release!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/projects/*/runs/*/exports/native-pdf*", async (route) => {
    attempts++;
    if (attempts === 1) return route.fulfill({ status: 503, json: { detail: "Native PDF service is unavailable. Please retry later." } });
    await held;
    await route.fulfill({ contentType: "application/pdf", body: bytes });
  });
  await open(page);
  await panel(page).getByRole("button", { name: "Download native PDF", exact: true }).click();
  await expect(panel(page).getByRole("alert")).toContainText("Native PDF service is unavailable. Please retry later.");
  await page.clock.install();
  await page.evaluate(() => {
    const tracked = { created: [] as string[], revoked: [] as string[] };
    (window as unknown as { pdfURLs: typeof tracked }).pdfURLs = tracked;
    const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
    URL.createObjectURL = (blob) => { const url = create(blob); tracked.created.push(url); return url; };
    URL.revokeObjectURL = (url) => { tracked.revoked.push(url); revoke(url); };
  });
  await panel(page).getByRole("button", { name: "Retry native PDF download" }).click();
  const preparing = panel(page).getByRole("button", { name: "Preparing native PDF…", exact: true });
  await expect(preparing).toBeDisabled();
  await expect(panel(page)).toHaveAttribute("aria-busy", "true");
  // Dispatching a click cannot start a second request while one is in flight.
  await preparing.dispatchEvent("click");
  expect(attempts).toBe(2);
  const event = page.waitForEvent("download");
  release();
  const download = await event;
  expect(await readFile((await download.path())!)).toEqual(bytes);
  await expect(panel(page).getByRole("status")).toHaveText("Native PDF download started.");
  await page.clock.fastForward(10_001);
  const urls = await page.evaluate(() => (window as unknown as { pdfURLs: { created: string[]; revoked: string[] } }).pdfURLs);
  expect(urls.created).toHaveLength(1);
  expect(urls.revoked).toEqual(urls.created);
});

test("an old run's in-flight result is discarded after changing selection", async ({ page }) => {
  await page.route("**/api/reporting/native-pdf/capability", (route) => route.fulfill({ json: capability(true) }));
  let release!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/projects/*/runs/*/exports/native-pdf*", async (route) => {
    await held;
    await route.fulfill({ contentType: "application/pdf", body: bytes });
  });
  await open(page, { multiple: true });
  await page.evaluate(async () => {
    const { exportAPI } = await import("/src/client.ts");
    const original = exportAPI.nativePDF;
    const tracked = { settled: false };
    (window as unknown as { pdfRequest: typeof tracked }).pdfRequest = tracked;
    exportAPI.nativePDF = async (...args: Parameters<typeof original>) => {
      try { return await original(...args); }
      finally { tracked.settled = true; }
    };
  });
  await panel(page).getByRole("button", { name: "Download native PDF", exact: true }).click();
  await expect(panel(page).getByRole("button", { name: "Preparing native PDF…", exact: true })).toBeDisabled();
  await page.getByRole("combobox", { name: "Numerical export run", exact: true }).selectOption("run-complete-a");
  await expect(panel(page).getByRole("button", { name: "Download native PDF", exact: true })).toBeEnabled();
  const received = page.waitForResponse((response) => response.url().includes("/exports/native-pdf"));
  const downloads: string[] = [];
  page.on("download", (download) => downloads.push(download.suggestedFilename()));
  release();
  await (await received).finished();
  // Await the real client's Blob/signature validation, without timing sleeps.
  await page.waitForFunction(() => (window as unknown as { pdfRequest: { settled: boolean } }).pdfRequest.settled);
  expect(downloads).toEqual([]);
  await expect(panel(page).getByRole("status")).toHaveCount(0);
});

test("frontend denial and absence of completed runs offer no native PDF action", async ({ page }) => {
  let capabilities = 0, downloads = 0;
  await page.route("**/api/reporting/native-pdf/capability", (route) => { capabilities++; return route.fulfill({ json: capability(true) }); });
  await page.route("**/api/projects/*/runs/*/exports/native-pdf*", (route) => { downloads++; return route.fulfill({ contentType: "application/pdf", body: bytes }); });
  await open(page, { hint: false });
  await expect(panel(page)).toContainText("Native PDF download is unavailable with the current feature settings.");
  await expect(panel(page).getByRole("button")).toHaveCount(0);
  expect(capabilities).toBe(0);
  expect(downloads).toBe(0);
  await page.keyboard.press("Alt+0");
  await page.evaluate(async () => {
    const { uiStore } = await import("/src/state/store.tsx");
    const current = uiStore.getState();
    uiStore.setState({ ...current, state: { ...current.state, view: { ...current.state.view, bundle: { ...current.state.view.bundle, simulation_runs: [] } } } });
  });
  await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
  await expect(page.getByText("Complete a simulation before exporting numerical results.", { exact: true })).toBeVisible();
  await expect(panel(page)).toHaveCount(0);
  expect(downloads).toBe(0);
});

test("disabled native PDF preserves independent HTML snapshot and CSV downloads", async ({ page }) => {
  let nativeRequests = 0;
  const zip = Buffer.from([80, 75, 3, 4, 0, 255, 128]); // Transport sentinel; existing CSV suite validates ZIP contents.
  await page.route("**/api/reporting/native-pdf/capability", (route) => route.fulfill({ json: capability(false) }));
  await page.route("**/api/projects/*/runs/*/exports/native-pdf*", (route) => { nativeRequests++; return route.abort(); });
  await page.route("**/api/projects/*/runs/*/exports", (route) => {
    expect(route.request().postDataJSON()).toEqual({ format: "csv", resolution: "hourly", level: "project", columns: ["pcc_power_w"], formats: ["csv"], deliverable: true });
    return route.fulfill({ contentType: "application/zip", body: zip });
  });
  await open(page);
  await page.getByRole("button", { name: "Preview report", exact: true }).click();
  const iframe = page.locator('iframe[title="Report preview"]');
  await expect(iframe).toHaveAttribute("data-report-snapshot-id", /\S+/);
  const htmlEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download HTML", exact: true }).click();
  const html = await htmlEvent;
  expect(html.suggestedFilename()).toMatch(/\.html$/);
  expect(await readFile((await html.path())!, "utf8")).toBe(await iframe.getAttribute("srcdoc"));
  const csvEvent = page.waitForEvent("download");
  await page.locator("[data-csv-export]").getByRole("button", { name: "Download CSV ZIP", exact: true }).click();
  const csv = await csvEvent;
  expect(csv.suggestedFilename()).toBe("RawiBumi_results_bundle.zip");
  expect(await readFile((await csv.path())!)).toEqual(zip);
  expect(nativeRequests).toBe(0);
});
