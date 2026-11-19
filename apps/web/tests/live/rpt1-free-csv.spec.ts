import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { inflateRawSync } from "node:zlib";

const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("RPT1 requires the disposable live API");
const ROOT = path.resolve(process.cwd(), "../..");
function unzip(buffer: Buffer): Map<string, Buffer> {
  const entries = new Map<string, Buffer>();
  let at = 0;
  while (buffer.readUInt32LE(at) === 0x04034b50) {
    const method = buffer.readUInt16LE(at + 8), size = buffer.readUInt32LE(at + 18);
    const nameLength = buffer.readUInt16LE(at + 26), extra = buffer.readUInt16LE(at + 28);
    const name = buffer.subarray(at + 30, at + 30 + nameLength).toString();
    const data = buffer.subarray(at + 30 + nameLength + extra, at + 30 + nameLength + extra + size);
    entries.set(name, method === 0 ? Buffer.from(data) : inflateRawSync(data));
    at += 30 + nameLength + extra + size;
  }
  return entries;
}

test("Free CSV downloads stored intervals and reconciles with Results PR", async ({ page, request }) => {
  const name = `=1+1 RPT1 ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(created.ok()).toBe(true);
  const id = (await created.json()).bundle.project.project_id, url = `${API}/api/projects/${id}`;
  try {
    const roof = await request.post(url + "/surfaces/rectangle", { data: { name: "@SUM RPT1 roof", width_m: 1 + 18 * 1.154 - .01, height_m: 3.45, base_elevation_m: 6.1 } });
    expect(roof.ok()).toBe(true);
    const sid = (await roof.json()).bundle.scene.surfaces[0].surface_id;
    expect((await request.post(url + "/pv-fields", { data: { name: "+cmd RPT1 array", support_surface_id: sid, module_definition_revision_id: "mod-rawibumi-uat-550-r1", tilt_deg: 10, row_pitch_m: 3.2, perimeter_setback_m: .5 } })).ok()).toBe(true);
    const inverter = await request.post(url + "/inverters", { data: { name: "INV", inverter_definition_revision_id: "inv-rawibumi-uat-150k-r1" } });
    expect(inverter.ok()).toBe(true);
    const iid = (await inverter.json()).bundle.electrical_design.inverter_instances[0].inverter_instance_id;
    const strings = await request.post(url + "/strings", { data: { string_length: 18, allow_shorter_remainder: false } });
    expect(strings.ok()).toBe(true);
    const ids = (await strings.json()).bundle.electrical_design.strings.map((s: { string_id: string }) => s.string_id);
    expect(ids).toHaveLength(1);
    expect((await request.post(url + "/assignments", { data: { inverter_instance_id: iid, string_ids: ids } })).ok()).toBe(true);
    execFileSync(path.join(ROOT, ".venv/bin/python"), ["-c", `
from pathlib import Path
import sys
from apps.api.server import create_app
root=Path(sys.argv[1]).resolve();store=root/'tmp/live-projects'
assert store.is_dir() and store.resolve()==store
app=create_app(store_root=store,library_root=root/'tmp/component-library')
app.state.study_service.acquire_weather(sys.argv[2],source_id='open_meteo_archive_era5',start_date='2025-01-01',end_date='2025-01-01',raw_response=(root/'tests/fixtures/weather/open_meteo_era5_phase60d_uat_padded_s10.json').read_bytes())
`, ROOT, id], { cwd: ROOT, timeout: 30_000 });
    await page.goto("/"); await page.locator(".start__row", { hasText: name }).click();
    await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+9");
    const simulated = page.waitForResponse(r => r.url().endsWith(`/projects/${id}/simulate`) && r.request().method() === "POST");
    await page.getByRole("button", { name: "Validate and run", exact: true }).click();
    const response = await simulated; expect(response.ok()).toBe(true); const record = await response.json();
    await page.keyboard.press("Alt+0"); await expect(page.locator(".kpis")).toBeVisible();
    const shownPR = Number(await page.locator(".kpis > div").nth(2).locator("strong").textContent());
    expect(shownPR).toBeCloseTo(record.summary_result.performance_ratio * 100, 1);
    await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
    await expect(page.getByRole("button", { name: "Download Free CSV", exact: true })).toBeVisible();
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download Free CSV", exact: true }).click();
    const file = await download;
    expect(file.suggestedFilename()).toBe("RawiBumi_free_csv.zip");
    const entries = unzip(await readFile((await file.path())!));
    expect([...entries.keys()]).toEqual(["rawibumi_free.csv", "export-manifest.json"]);
    const csv = entries.get("rawibumi_free.csv")!.toString(), rows = csv.trimEnd().split("\n");
    expect(rows[0]).toBe("timestamp,ghi_wm2,dni_wm2,dhi_wm2,poa_wm2,t_ambient_c,t_cell_c,e_dc_inverter_kwh,e_ac_pcc_kwh,pr");
    expect(rows).toHaveLength(25); expect(rows.every(row => row.split(",").length === 10)).toBe(true);
    for (const hostile of [name, "@SUM RPT1 roof", "+cmd RPT1 array"]) expect(csv).not.toContain(hostile);
    const manifest = JSON.parse(entries.get("export-manifest.json")!.toString());
    expect(manifest.row_count).toBe(24); expect(manifest.aggregates.period.scope).toBe("period");
    expect(manifest.aggregates.period.pr).toBeCloseTo(record.summary_result.performance_ratio, 9);
    expect(manifest.aggregates.period.pr * 100).toBeCloseTo(shownPR, 1);
    await expect(page.locator("[data-csv-export]")).toBeVisible();
  } finally { expect((await request.delete(url, { params: { confirm: id } })).ok()).toBe(true); }
});
