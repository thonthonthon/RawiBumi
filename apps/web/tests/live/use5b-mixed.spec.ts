import { expect, test as base } from "@playwright/test";
import { execFileSync, spawn } from "node:child_process";
import path from "node:path";
import { once } from "node:events";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";

let API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000"))
  throw new Error("USE5B requires a disposable API on a free port, never 8000.");
const ROOT = process.env.RAWIBUMI_REPO_ROOT ?? path.resolve(process.cwd(), "../..");

const test=base.extend<{}, {isolatedMixedApi:{api:string;directory:string}}>({
 isolatedMixedApi:[async({},use,workerInfo)=>{
  mkdirSync(path.join(ROOT,"tmp"),{recursive:true});
  const directory=mkdtempSync(path.join(ROOT,"tmp","use5b-mixed-live-"));
  const script=`import runpy
from pathlib import Path
runpy.run_path("apps/web/scripts/serve-live-test-api.py",run_name="use5b_test_catalog")
from apps.api.server import create_app
import uvicorn
uvicorn.run(create_app(store_root=Path(${JSON.stringify(directory)})/"projects",library_root=Path(${JSON.stringify(directory)})/"component-library"),host="127.0.0.1",port=0,timeout_keep_alive=75)
`;
  const child=spawn(path.join(ROOT,".venv/bin/python"),["-c",script],{cwd:ROOT,stdio:["ignore","pipe","pipe"],env:{...process.env,PYTHONSTARTUP:undefined,PYTHONDONTWRITEBYTECODE:"1",RAWIBUMI_PROJECT_STORE:path.join(directory,"bootstrap-projects")}});
  let logs="";
  try{
   API=await new Promise<string>((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error(`USE5B isolated API startup timed out: ${logs}`)),20000);
    const data=(chunk:Buffer)=>{
     logs+=chunk.toString();
     const address=logs.match(/Uvicorn running on (http:\/\/127\.0\.0\.1:\d+)/);
     if(address){
      clearTimeout(timer);
      if(new URL(address[1]).port==="8000")reject(new Error("USE5B must never use port 8000"));
      else resolve(address[1]);
     }
    };
    child.stdout.on("data",data);child.stderr.on("data",data);
    child.once("error",error=>{clearTimeout(timer);reject(error);});
    child.once("exit",code=>{clearTimeout(timer);reject(new Error(`USE5B isolated API exited ${code}: ${logs}`));});
   });
   await use({api:API,directory});
  }finally{
   if(child.exitCode===null&&child.signalCode===null){
    const closed=once(child,"exit");
    const kill=setTimeout(()=>child.kill("SIGKILL"),15000);
    child.kill("SIGTERM");
    try{await closed;}finally{clearTimeout(kill);}
   }
   mkdirSync(workerInfo.project.outputDir,{recursive:true});
   writeFileSync(path.join(workerInfo.project.outputDir,`use5b-api-${workerInfo.workerIndex}.log`),logs);
   rmSync(directory,{recursive:true,force:true});
   writeFileSync(path.join(workerInfo.project.outputDir,`use5b-isolation-${workerInfo.workerIndex}.json`),JSON.stringify({api:API,directory,pid:child.pid,exitCode:child.exitCode,signalCode:child.signalCode,store:"projects",library:"component-library",teardown:"removed"},null,2));
  }
 },{scope:"worker",auto:true}],
 page:async({page,isolatedMixedApi},use)=>{
  await page.route("**/api/**",async route=>{
   const source=new URL(route.request().url());
   // Preserve the original browser request's lack of an extra HTTP deadline;
   // Playwright's unchanged whole-test budget is the bound.
   const response=await route.fetch({url:isolatedMixedApi.api+source.pathname+source.search,timeout:0});
   await route.fulfill({response});
  });
  await use(page);
  // A request still in flight when the test ends must not fail the fixture (Playwright's advice).
  await page.unrouteAll({behavior:"ignoreErrors"});
 }
});

// A composite string on MPPT 1, plus two uniform strings facing different ways on MPPT 2.
test("mixed strings and a mixed MPPT simulate and show recorded Results diagnostics", async ({ page, request, isolatedMixedApi }) => {
  test.setTimeout(120_000);
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  const name = `USE5B ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8,
    timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(created.ok(), await created.text()).toBe(true);
  const id: string = (await created.json()).bundle.project.project_id, url = `${API}/api/projects/${id}`;
  try {
    const fields: string[] = [];
    for (const [i, tilt] of [10, 14].entries()) {
      const roof = await request.post(url + "/surfaces/rectangle", { data: { name: `Roof ${i+1}`, origin_x_m: i*40,
        width_m: 1+15*1.154-.01, height_m: 3.45, base_elevation_m: 6.1 } });
      expect(roof.ok(), await roof.text()).toBe(true);
      const surface = (await roof.json()).bundle.scene.surfaces[i].surface_id;
      const field = await request.post(url + "/pv-fields", { data: { name: `PV ${i+1}`, support_surface_id: surface,
        module_definition_revision_id: "mod-rawibumi-uat-550-r1", tilt_deg: tilt, row_pitch_m: 3.2, perimeter_setback_m: .5 } });
      expect(field.ok(), await field.text()).toBe(true);
      fields.push((await field.json()).bundle.scene.pv_fields[i].pv_field_id);
    }
    const inverter = await request.post(url + "/inverters", { data: { name: "Mixed inverter", inverter_definition_revision_id: "inv-rawibumi-uat-150k-r1" } });
    expect(inverter.ok(), await inverter.text()).toBe(true);
    const view = await inverter.json();
    const modules = fields.map(f => view.bundle.scene.module_instances.filter((m: {pv_field_id: string}) => m.pv_field_id === f)
      .map((m: {module_instance_id: string}) => m.module_instance_id) as string[]);
    expect(modules.map(ids => ids.length)).toEqual([15, 15]);
    const mppts = view.bundle.electrical_design.mppt_instances.sort((a: {index: number}, b: {index: number}) => a.index-b.index);
    const command = (command_type: string, parameters: unknown) => ({ schema_name: "ElectricalTopologyCommand", schema_version: "0.1",
      command_id: `use5b-${command_type}-${Math.random()}`, command_type, parameters });
    const configured = await request.post(url + "/electrical/commands", { data: { commands: [
      command("create_string", { string_id: "composite", module_instance_ids: [...modules[0].slice(0,5), ...modules[1].slice(0,5)] }),
      command("create_string", { string_id: "roof-a", module_instance_ids: modules[0].slice(5) }),
      command("create_string", { string_id: "roof-b", module_instance_ids: modules[1].slice(5) }),
      command("assign_strings_to_mppt", { mppt_instance_id: mppts[0].mppt_instance_id, string_ids: ["composite"] }),
      command("assign_strings_to_mppt", { mppt_instance_id: mppts[1].mppt_instance_id, string_ids: ["roof-a", "roof-b"] })
    ] } });
    expect(configured.ok(), await configured.text()).toBe(true);
    execFileSync(path.join(ROOT, ".venv/bin/python"), ["-c", `
from pathlib import Path
import sys
from apps.api.server import create_app
root=Path(sys.argv[1]).resolve()
directory=Path(sys.argv[3]).resolve()
assert directory.parent==root/'tmp' and directory.name.startswith('use5b-mixed-live-')
store=directory/'projects'
assert store.is_dir() and store.resolve()==store
app=create_app(store_root=store,library_root=directory/'component-library')
app.state.study_service.acquire_weather(sys.argv[2],source_id='open_meteo_archive_era5',
    start_date='2025-01-01',end_date='2025-01-01',
    raw_response=(root/'tests/fixtures/weather/open_meteo_era5_phase60d_uat_padded_s10.json').read_bytes())
`, ROOT, id, isolatedMixedApi.directory], { cwd: ROOT, timeout: 30_000, env: { ...process.env, PYTHONSTARTUP: undefined, PYTHONDONTWRITEBYTECODE: "1", RAWIBUMI_PROJECT_STORE: path.join(isolatedMixedApi.directory, "bootstrap-projects") } });
    const readiness = await request.get(url + "/execution-readiness");
    const ready = await readiness.json();
    expect(ready.ready, JSON.stringify(ready.findings)).toBe(true);
    expect(ready.findings.some((f: {rule_id: string}) => f.rule_id === "SIMULATION_SCOPE_MIXED_STRINGS_ON_ONE_MPPT")).toBe(false);

    await page.addInitScript(() => window.localStorage.setItem("rawibumi.language", "en"));
    await page.route("https://nominatim.openstreetmap.org/**", route => route.abort());
    await page.goto("/"); await page.locator(".start__row", { hasText: name }).click();
    await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+9");
    const simulated = page.waitForResponse(r => r.url().endsWith(`/projects/${id}/simulate`) && r.request().method() === "POST");
    await page.getByRole("button", { name: "Validate and run", exact: true }).click();
    const response = await simulated;
    expect(response.ok(), await response.text()).toBe(true);
    const run = await response.json();
    expect(["completed", "completed_with_warnings"]).toContain(run.status);
    expect(run.mixed_orientation.mixed_string_ids).toContain("composite");
    expect(run.mixed_orientation.mixed_mppt_instance_ids).toEqual(mppts.map((m: {mppt_instance_id: string}) => m.mppt_instance_id).sort());
    const loss = run.summary_result.loss_summary.find((l: {loss_type: string}) => l.loss_type === "orientation_mismatch");
    expect(loss.lost_energy_wh).toBeGreaterThan(0);
    expect(loss.lost_energy_wh/loss.reference_energy_wh).toBeLessThan(.05);

    await page.keyboard.press("Alt+0");
    await page.getByLabel("Run").selectOption(run.simulation_run_id);
    await expect(page.locator("[data-mixed-orientation-result]")).toContainText("Mixed orientation simulated — beyond what PVsyst/HelioScope simulate.");
    await expect(page.locator("[data-mixed-orientation-result]")).toContainText("Ideal MPPT: the highest power peak.");
    const diagnostics = page.locator("[data-mixed-diagnostics]");
    await expect(diagnostics).toContainText("Diagnostics only — the result uses the highest peak.");
    await expect(diagnostics.locator("[data-mixed-coverage]")).toHaveAttribute("data-mixed-coverage", "partial");
    await expect(diagnostics.locator("[data-mixed-total] [data-multi-peak-hours]")).toHaveAttribute("data-multi-peak-hours", String(run.mixed_orientation.period_totals.multi_peak_duration_hours));
    for (const key of ["simple_tracker", "second_highest", "lowest"]) {
      await expect(diagnostics.locator(`[data-mixed-total] [data-tracker-gap="${key}"]`)).toHaveAttribute("data-gap-wh", String(run.mixed_orientation.period_totals.energy_gaps_wh[key]));
    }
    await page.locator(".results__tabs").getByRole("radio", { name: "Loss waterfall", exact: true }).click();
    const row = page.locator('[data-loss-type="orientation_mismatch"]');
    await expect(row).toContainText("Orientation mismatch");
    await expect(row.locator("[data-loss-wh]")).toHaveAttribute("data-loss-wh", String(loss.lost_energy_wh));
    const persisted = await request.get(url + `/runs/${run.simulation_run_id}/result`);
    expect(persisted.ok(), await persisted.text()).toBe(true);
    expect((await persisted.json()).mixed_orientation).toEqual(run.mixed_orientation);
    expect(errors).toEqual([]);
  } finally {
    expect((await request.delete(url, { params: { confirm: id } })).ok()).toBe(true);
  }
});
