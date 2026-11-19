import { expect, test as base } from "@playwright/test";
import { execFileSync, spawn } from "node:child_process";
import { once } from "node:events";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const ROOT = path.resolve(process.cwd(), "../..");
const test = base.extend<{}, { pdfApi: { api: string; directory: string } }>({
  pdfApi: [async ({}, use, workerInfo) => {
    const directory = mkdtempSync(path.join(tmpdir(), "rpt2b2-live-"));
    const script = `import runpy\nfrom pathlib import Path\nrunpy.run_path('apps/web/scripts/serve-live-test-api.py',run_name='rpt2b2_test_catalog')\nfrom apps.api.server import create_app\nimport uvicorn\nroot=Path(${JSON.stringify(directory)})\nuvicorn.run(create_app(store_root=root/'projects',library_root=root/'component-library'),host='127.0.0.1',port=0,timeout_keep_alive=75)\n`;
    const child = spawn(path.join(ROOT, ".venv/bin/python"), ["-u", "-c", script], { cwd: ROOT, stdio: ["ignore", "pipe", "pipe"], env: {
      ...process.env, PYTHONSTARTUP: "", RAWIBUMI_PROJECT_STORE: path.join(directory, "projects"), RAWIBUMI_DEPLOYMENT_EDITION: "community_self_hosted", RAWIBUMI_COMMUNITY_NATIVE_PDF_ENABLED: "1",
      RAWIBUMI_PDF_RUNTIME_ROOT: path.join(ROOT, "apps/web"), RAWIBUMI_PDF_CHROMIUM_EXECUTABLE: path.join(process.env.HOME!, ".cache/ms-playwright/chromium-1248/chrome-linux64/chrome"), RAWIBUMI_PDF_NODE: process.execPath
    } });
    let logs = "";
    try {
      const api = await new Promise<string>((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error(`PDF API startup timed out: ${logs}`)), 20000);
        const data = (chunk: Buffer) => {
          logs += chunk.toString(); const match = logs.match(/Uvicorn running on (http:\/\/127\.0\.0\.1:\d+)/);
          if (match) { clearTimeout(timer); if (new URL(match[1]).port === "8000") reject(new Error("Forbidden API port")); else resolve(match[1]); }
        };
        child.stdout.on("data", data); child.stderr.on("data", data);
        child.once("error", error => { clearTimeout(timer); reject(error); });
        child.once("exit", code => { clearTimeout(timer); reject(new Error(`PDF API exited ${code}: ${logs}`)); });
      });
      await use({ api, directory });
    } finally {
      if (child.exitCode === null && child.signalCode === null) {
        const closed = once(child, "exit"), timer = setTimeout(() => child.kill("SIGKILL"), 15000);
        child.kill("SIGTERM"); try { await closed; } finally { clearTimeout(timer); }
      }
      mkdirSync(workerInfo.project.outputDir, { recursive: true });
      writeFileSync(path.join(workerInfo.project.outputDir, `rpt2b2-api-${workerInfo.workerIndex}.log`), logs);
      rmSync(directory, { recursive: true, force: true });
    }
  }, { scope: "worker" }],
  page: async ({ page, pdfApi }, use) => {
    await page.route("**/api/**", async route => {
      const source = new URL(route.request().url());
      const response = await route.fetch({ url: pdfApi.api + source.pathname + source.search, timeout: 0 });
      await route.fulfill({ response });
    });
    await use(page); await page.unrouteAll({ behavior: "ignoreErrors" });
  }
});

test("browser and protected PDF share verified period results, charts, method and illustrative plan in both locales", async ({ page, request, pdfApi }) => {
  await page.addInitScript(() => { localStorage.setItem("rawibumi.addressLookup", "off"); localStorage.setItem("rawibumi.language", "en"); });
  const name = `RPT2b2 ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${pdfApi.api}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(created.status()).toBe(201); const initial = await created.json(), id = initial.bundle.project.project_id, url = `${pdfApi.api}/api/projects/${id}`;
  try {
    const module = initial.catalog.modules.find((m: { simulation_ready: boolean }) => m.simulation_ready); expect(module).toBeDefined();
    const roof = await request.post(url + "/surfaces/rectangle", { data: { name: "Synthetic PDF roof", width_m: 1 + 18 * (module.width_m + .02) - .01, height_m: module.height_m + 1.1, base_elevation_m: 6.1 } });
    expect(roof.ok()).toBe(true); const sid = (await roof.json()).bundle.scene.surfaces[0].surface_id;
    expect((await request.post(url + "/pv-fields", { data: { name: "Synthetic PDF array", support_surface_id: sid, module_definition_revision_id: module.revision_id, tilt_deg: 10, row_pitch_m: 3.2, perimeter_setback_m: .5 } })).ok()).toBe(true);
    const inverter = await request.post(url + "/inverters", { data: { name: "PDF inverter", inverter_definition_revision_id: "inv-rawibumi-uat-150k-r1" } });
    expect(inverter.ok()).toBe(true); const iid = (await inverter.json()).bundle.electrical_design.inverter_instances[0].inverter_instance_id;
    const strings = await request.post(url + "/strings", { data: { string_length: 18, allow_shorter_remainder: false } });
    expect(strings.ok()).toBe(true); const ids = (await strings.json()).bundle.electrical_design.strings.map((s: { string_id: string }) => s.string_id);
    expect(ids).toHaveLength(1); expect((await request.post(url + "/assignments", { data: { inverter_instance_id: iid, string_ids: ids } })).ok()).toBe(true);
    execFileSync(path.join(ROOT, ".venv/bin/python"), ["-c", `
from pathlib import Path
import sys,numpy as np,pandas as pd,pvlib
from apps.api.server import create_app
from weather.core import build_weather_dataset,build_time_semantics
root=Path(sys.argv[1]);app=create_app(store_root=root/'projects',library_root=root/'component-library')
index=pd.date_range('2025-01-01',periods=24,freq='h',tz='Asia/Jakarta')
position=pvlib.solarposition.spa_python(index+pd.Timedelta(minutes=30),latitude=-6.2,longitude=106.8,altitude=0.,pressure=100500.,temperature=30.,delta_t=None,atmos_refract=.5667,how='numpy',numthreads=1)
cosz=np.maximum(np.cos(np.radians(position.zenith.to_numpy())),0.);dni=np.where(cosz>0,700.,0.);dhi=120.*cosz
series=pd.DataFrame({'ghi_w_m2':dhi+dni*cosz,'dni_w_m2':dni,'dhi_w_m2':dhi,'ambient_temperature_c':30.,'wind_speed_m_s':1.,'pressure_pa':100500.},index=index)
semantics=build_time_semantics(canonical_timezone='Asia/Jakarta',source_timestamp_convention='interval_start',native_interval_seconds=3600,current_interval_seconds=3600,source_timezone='Asia/Jakarta',source_utc_offset_hours=7.)
weather=build_weather_dataset(series,weather_dataset_id='rpt2b2-synthetic-weather',revision_id='rpt2b2-synthetic-weather-r1',name='Fictional PDF daylight weather',site_id='rpt2b2-synthetic-site',timezone='Asia/Jakarta',native_resolution_seconds=3600,source_format='synthetic_test',source_timestamp_convention='interval_start',location={'latitude_deg':-6.2,'longitude_deg':106.8,'elevation_m':0.},native_series_origin='unknown',series_origin='unknown',time_semantics=semantics,start_time=index[0],end_time=index[-1]+pd.Timedelta(hours=1))
bundle=app.state.project_service.get_bundle(sys.argv[2]);bundle['weather_selection']=app.state.study_service.weather.save(sys.argv[2],weather);app.state.project_service.save_bundle(bundle)
`, pdfApi.directory, id], { cwd: ROOT, env: { ...process.env, RAWIBUMI_PROJECT_STORE: path.join(pdfApi.directory, "projects") }, timeout: 30000 });
    await page.goto("/"); await page.locator(".start__row", { hasText: name }).click(); await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+9");
    const simulated = page.waitForResponse(r => r.url().endsWith(`/projects/${id}/simulate`) && r.request().method() === "POST");
    await page.getByRole("button", { name: "Validate and run", exact: true }).click();
    const response = await simulated; expect(response.ok()).toBe(true); const record = await response.json(); expect(record.summary_result.total_energy_wh).toBeGreaterThan(0);
    const pr = (record.summary_result.performance_ratio * 100).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    await expect(page.locator(".kpis")).toContainText(pr); await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
    await expect(page.getByRole("button", { name: "Preview report", exact: true })).toBeEnabled();
    const colours = await page.evaluate(async () => {
      const { reportToken } = await import("/src/report/tokens.ts");
      const names = ["role-panel-text", "role-panel-muted", "role-chart-grid", "role-chart-axis", "role-chart-1", "role-chart-2", "role-chart-loss", "font-ui", ...Array.from({length:8}, (_,i) => `color-mppt-paper-${i+1}`), ...Array.from({length:6}, (_,i) => `color-heat-${i}`)];
      return names.map(name => [reportToken(name), getComputedStyle(document.documentElement).getPropertyValue(`--rb-${name}`).trim()]);
    });
    for (const [parsed, computed] of colours) expect(parsed).toBe(computed);
    const snapshotResponse = await request.get(`${url}/runs/${record.simulation_run_id}/report-snapshot`); expect(snapshotResponse.ok()).toBe(true); const snapshot = await snapshotResponse.json();
    for (const locale of ["en", "id"] as const) {
      await page.evaluate(async language => (await import("/src/i18n/index.ts")).setLanguage(language), locale);
      const button = page.locator("[data-native-pdf-export]").getByRole("button", { name: locale === "en" ? "Download native PDF" : "Unduh PDF native", exact: true });
      await expect(button).toBeEnabled();
      const posted = page.waitForResponse(r => r.url().endsWith(`/runs/${record.simulation_run_id}/exports/native-pdf`) && r.request().method() === "POST");
      const event = page.waitForEvent("download"); await button.click(); const download = await event, pdfResponse = await posted;
      expect(pdfResponse.status(), pdfResponse.status() === 200 ? "" : await pdfResponse.text()).toBe(200);
      const figure = pdfResponse.request().postDataJSON().plan_figure_png; expect(figure).toMatch(/^data:image\/png;base64,/);
      const file = path.join(pdfApi.directory, `report-${locale}.pdf`); writeFileSync(file, await readFileSync((await download.path())!));
      const text = execFileSync(path.join(ROOT, ".venv/bin/python"), ["-c", `import pikepdf,sys,subprocess\nfrom pathlib import Path\np=Path(sys.argv[1]);out=p.with_suffix('.plain.pdf')\nwith pikepdf.open(p) as d:\n assert d.is_encrypted and d.encryption.R==6 and not d.allow.extract\n d.save(out,encryption=False)\nprint(subprocess.check_output(['pdftotext','-layout',str(out),'-'],text=True))`, file], { cwd: ROOT, encoding: "utf8" });
      expect(text).toContain(locale === "en" ? "RawiBumi · Free / Community report" : "RawiBumi · Laporan Free / Komunitas");
      expect(text.replace(/\s+/g, " ")).toContain(locale === "en" ? "Illustrative layout, drawn by the browser; not verified" : "Denah ilustratif, digambar oleh browser; tidak terverifikasi");
      expect(text.replace(/\s+/g, " ")).toContain(locale === "en" ? "Inverter temperature derating is not modelled" : "Derating suhu inverter tidak dimodelkan");
      expect(text.replace(/\s+/g, " ")).toContain(`${pr} %`);
      expect(text.replace(/\s+/g, "")).toContain(snapshot.snapshot_sha256);
      const browserHtml = await page.evaluate(async ({ snapshot, locale }) => (await import("/src/report/render.ts")).renderReport(snapshot, { locale, planFigurePng: null, watermark: "free_community" }), { snapshot, locale });
      const nodeHtml = execFileSync(process.execPath, ["-e", `const fs=require('node:fs');const s=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(require('./apps/web/dist/report-render/report-render.cjs').renderReport(s,{locale:process.argv[1],planFigurePng:null,watermark:'free_community'}))`, locale], { cwd: ROOT, input: JSON.stringify(snapshot), encoding: "utf8" });
      const contents = await page.evaluate(({ browserHtml, nodeHtml }) => {
        const read = (html: string) => { const doc = new DOMParser().parseFromString(html, "text/html"); doc.querySelectorAll("style,svg").forEach(n => n.remove()); return { text: doc.body.textContent!.replace(/\s+/g, " ").trim(), series: JSON.parse(doc.querySelector("main")!.getAttribute("data-report-chart-data")!) }; };
        return [read(browserHtml), read(nodeHtml)];
      }, { browserHtml, nodeHtml });
      expect(contents[0]).toEqual(contents[1]);
    }
  } finally { expect((await request.delete(url, { params: { confirm: id } })).ok()).toBe(true); }
});
