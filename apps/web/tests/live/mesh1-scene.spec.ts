import {expect,test as base} from "@playwright/test";
import {execFileSync,spawn} from "node:child_process";
import {once} from "node:events";
import {mkdirSync,mkdtempSync,rmSync,writeFileSync} from "node:fs";
import path from "node:path";
let API=process.env.RAWIBUMI_API;
if(!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000"))throw new Error("MESH1 requires the disposable test-only API.");
const ROOT=path.resolve(process.cwd(),"../..");
// Only this annual scenario gets a separate real API: other live files retain
// their shared service. The unmodified launcher supplies the test catalogue.
const test=base.extend<{}, {isolatedMeshApi:{api:string;directory:string}}>({
 isolatedMeshApi:[async({},use,workerInfo)=>{
  mkdirSync(path.join(ROOT,"tmp"),{recursive:true});
  const directory=mkdtempSync(path.join(ROOT,"tmp","mesh1-annual-live-"));
  const script=`import runpy
from pathlib import Path
runpy.run_path("apps/web/scripts/serve-live-test-api.py",run_name="mesh1_test_catalog")
from apps.api.server import create_app
import uvicorn
uvicorn.run(create_app(store_root=Path(${JSON.stringify(directory)})/"projects",library_root=Path(${JSON.stringify(directory)})/"component-library"),host="127.0.0.1",port=0,timeout_keep_alive=75)
`;
  const child=spawn(path.join(ROOT,".venv/bin/python"),["-c",script],{cwd:ROOT,stdio:["ignore","pipe","pipe"]});
  let logs="";
  try{
   API=await new Promise<string>((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error(`MESH1 isolated API startup timed out: ${logs}`)),20000);
    const data=(chunk:Buffer)=>{
     logs+=chunk.toString();
     const address=logs.match(/Uvicorn running on (http:\/\/127\.0\.0\.1:\d+)/);
     if(address){
      clearTimeout(timer);
      if(new URL(address[1]).port==="8000")reject(new Error("MESH1 must never use port 8000"));
      else resolve(address[1]);
     }
    };
    child.stdout.on("data",data);child.stderr.on("data",data);
    child.once("error",error=>{clearTimeout(timer);reject(error);});
    child.once("exit",code=>{clearTimeout(timer);reject(new Error(`MESH1 isolated API exited ${code}: ${logs}`));});
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
   writeFileSync(path.join(workerInfo.project.outputDir,`mesh1-api-${workerInfo.workerIndex}.log`),logs);
   rmSync(directory,{recursive:true,force:true});
   writeFileSync(path.join(workerInfo.project.outputDir,`mesh1-isolation-${workerInfo.workerIndex}.json`),JSON.stringify({api:API,directory,pid:child.pid,exitCode:child.exitCode,signalCode:child.signalCode,store:"projects",library:"component-library",teardown:"removed"},null,2));
  }
 },{scope:"worker",auto:true}],
 page:async({page,isolatedMeshApi},use)=>{
  await page.route("**/api/**",async route=>{
   const source=new URL(route.request().url());
   // Preserve the original browser request's lack of an extra HTTP deadline;
   // Playwright's unchanged 90-second whole-test budget is the bound.
   const response=await route.fetch({url:isolatedMeshApi.api+source.pathname+source.search,timeout:0});
   await route.fulfill({response});
  });
  await use(page);
  // A request still in flight when the test ends must not fail the fixture (Playwright's advice).
  await page.unrouteAll({behavior:"ignoreErrors"});
 }
});
test("exact stepped mesh and explicit tables display, string, simulate with shading, and delete atomically",async({page,request,isolatedMeshApi})=>{
 const name=`MESH1 synthetic ${Date.now()} ${Math.random()}`;
 const created=await request.post(`${API}/api/projects`,{data:{name,latitude_deg:-6.425,longitude_deg:106.831,elevation_m:93,timezone:"Asia/Jakarta",workspace_mode:"blank_engineering_plane"}});
 expect(created.status()).toBe(201);const initial=await created.json(),pid=initial.bundle.project.project_id,url=`${API}/api/projects/${pid}`;
 const module=initial.catalog.modules.find((m:{revision_id:string})=>m.revision_id==="mod-rawibumi-uat-550-r1");expect(module).toBeDefined();
 const operations=[
  {operation_id:"mesh",operation_type:"create_mesh",obstacle_id:"stepped",scene_object_id:"obj-stepped",name:"Stepped overhang",mesh:{vertices_m:[[0,-1,5],[5,-1,5],[5,4,5],[0,4,5],[5,-1,7],[8,-1,7],[8,4,7],[5,4,7]],faces:[[0,1,2,3],[1,4,7,2],[4,5,6,7]]},provenance:{source_id:"synthetic-live"}},
  {operation_id:"tables",operation_type:"create_explicit_field",pv_field_id:"tables",name:"Explicit tables",tables:[{table_id:"table-main",anchor_xyz_m:[0,0,3],anchor_convention:"lower_left",tilt_deg:10,azimuth_deg:180,module_definition_revision_id:module.revision_id,modules_across:18,modules_up:1,module_orientation:"portrait",module_gap_across_m:.02,module_gap_up_m:.02}],provenance:{source_id:"synthetic-live"}}
 ];
 const preview=await request.post(url+"/scene/geometry",{data:{operations,dry_run:true}});expect(preview.ok()).toBe(true);expect((await preview.json()).after.module_count).toBe(18);
 expect((await (await request.get(url)).json()).bundle.scene.module_instances).toHaveLength(0);
 const added=await request.post(url+"/scene/geometry",{data:{operations}});expect(added.ok()).toBe(true);
 const view=await added.json();expect(view.bundle.project.project_revision.revision_number).toBe(initial.bundle.project.project_revision.revision_number+1);
 const derived=await (await request.get(url+"/scene/geometry-3d")).json();expect(derived.obstacles[0].mesh.vertices_3d).toEqual(operations[0].mesh!.vertices_m);expect(derived.modules).toHaveLength(18);
 // HTTP undo remains explicitly unavailable; session history is covered in Python.
 const unchanged=await (await request.get(url)).json();
 const undo=await request.post(url+"/scene/commands",{data:{command:{schema_name:"SceneEditorCommand",schema_version:"0.1",command_id:"undo",command_type:"undo",target_entity_ids:[],parameters:{}}}});
 expect(undo.status()).toBe(422);expect(await undo.text()).toContain("HTTP undo needs persisted history");expect(await (await request.get(url)).json()).toEqual(unchanged);
 const inverter=await request.post(url+"/inverters",{data:{name:"MESH1 inverter",inverter_definition_revision_id:"inv-rawibumi-uat-150k-r1"}});expect(inverter.ok()).toBe(true);
 const iid=(await inverter.json()).bundle.electrical_design.inverter_instances[0].inverter_instance_id;
 const strings=await request.post(url+"/strings",{data:{string_length:18,allow_shorter_remainder:false}});expect(strings.ok()).toBe(true);
 const ids=(await strings.json()).bundle.electrical_design.strings.map((s:{string_id:string})=>s.string_id);expect(ids).toHaveLength(1);
 expect((await request.post(url+"/assignments",{data:{inverter_instance_id:iid,string_ids:ids}})).ok()).toBe(true);
 execFileSync(path.join(ROOT,".venv/bin/python"),["-c",`
from pathlib import Path
import sys
from apps.api.server import create_app
root=Path(sys.argv[1]).resolve();directory=Path(sys.argv[3]).resolve();store=directory/'projects'
assert directory.parent==root/'tmp' and directory.name.startswith('mesh1-annual-live-')
assert store.is_dir() and store.resolve()==store
app=create_app(store_root=store,library_root=directory/'component-library')
# Entirely fictional full-year weather, constructed in-test. No network/private inputs.
import numpy as np
import pandas as pd
import pvlib
from weather.core import build_weather_dataset,build_time_semantics
index=pd.date_range('2023-01-01',periods=8760,freq='h',tz='Asia/Jakarta')
position=pvlib.solarposition.spa_python(index+pd.Timedelta(minutes=30),latitude=-6.425,longitude=106.831,altitude=93.,pressure=100500.,temperature=30.,delta_t=None,atmos_refract=.5667,how='numpy',numthreads=1)
cosz=np.maximum(np.cos(np.radians(position['zenith'].to_numpy())),0.);dni=np.where(cosz>0,700.,0.);dhi=120.*cosz
series=pd.DataFrame({'ghi_w_m2':dhi+dni*cosz,'dni_w_m2':dni,'dhi_w_m2':dhi,'ambient_temperature_c':30.,'wind_speed_m_s':1.,'pressure_pa':100500.},index=index)
semantics=build_time_semantics(canonical_timezone='Asia/Jakarta',source_timestamp_convention='interval_start',native_interval_seconds=3600,current_interval_seconds=3600,source_timezone='Asia/Jakarta',source_utc_offset_hours=7.)
weather=build_weather_dataset(series,weather_dataset_id='mesh1-live-synthetic-weather',revision_id='mesh1-live-synthetic-weather-r1',name='Entirely fictional MESH1 live annual weather',site_id='mesh1-synthetic-site',timezone='Asia/Jakarta',native_resolution_seconds=3600,source_format='synthetic_test',source_timestamp_convention='interval_start',location={'latitude_deg':-6.425,'longitude_deg':106.831,'elevation_m':93.},native_series_origin='unknown',series_origin='unknown',time_semantics=semantics,start_time=index[0],end_time=index[-1]+pd.Timedelta(hours=1))
bundle=app.state.project_service.get_bundle(sys.argv[2]);bundle['weather_selection']=app.state.study_service.weather.save(sys.argv[2],weather);app.state.project_service.save_bundle(bundle)
`,ROOT,pid,isolatedMeshApi.directory],{cwd:ROOT,timeout:30_000});
 const errors:string[]=[];page.on("pageerror",error=>errors.push(error.message));
 await page.goto("/");await page.locator(".start__row",{hasText:name}).click();await expect(page.locator(".rail")).toBeVisible();
 await page.keyboard.press("Alt+4");await expect(page.locator(".taskpanel")).toContainText("Explicit layout: 1 tables, 18 modules");
 const field=page.locator(".card-row",{has:page.getByText("Explicit tables",{exact:true})});await expect(field.getByRole("button",{name:"Re-fill",exact:true})).toBeDisabled();
 const response=page.waitForResponse(r=>r.url().endsWith(`/projects/${pid}/scene/geometry-3d`) && r.request().method()==="GET");
 await page.getByRole("button",{name:"Isometric",exact:true}).click();expect((await response).ok()).toBe(true);
 await expect(page.getByRole("status").filter({hasText:"Meshes and explicit tables: exact engine geometry, read-only."})).toBeVisible();
 await expect(page.locator(".view3d__canvas")).toBeVisible();await expect(page.locator(".plan__nogl")).toHaveCount(0);
 // Actual drawing inputs equal the derived artifact, with no table-sized filler.
 const drawing=await page.evaluate(async data=>{
  const {buildExactGeometry,disposeGroup}=await import("/src/canvas/gl/scene3d.ts");const group=buildExactGeometry(data,new Set(["tables"]));
  const names=group.children.filter(x=>x.type==="Mesh").map(x=>x.name);disposeGroup(group);return names;
 },derived);expect(drawing).toEqual(["stepped",...derived.modules.map((m:{module_instance_id:string})=>m.module_instance_id)]);
 await page.keyboard.press("Alt+9");const ready=await request.get(url+"/execution-readiness");expect((await ready.json()).ready).toBe(true);
 const runResponse=page.waitForResponse(r=>r.url().endsWith(`/projects/${pid}/simulate`) && r.request().method()==="POST");
 await expect(page.getByRole("button",{name:"Validate and run",exact:true})).toBeEnabled();await page.getByRole("button",{name:"Validate and run",exact:true}).click();expect((await runResponse).ok()).toBe(true);
 await expect(page.getByRole("heading",{name:"Results",exact:true})).toBeVisible();
 const saved=(await (await request.get(url)).json()).bundle.simulation_runs;expect(saved).toHaveLength(1);expect(saved[0].status).toMatch(/^completed/);
 expect(saved[0].summary_result.period_duration_hours).toBe(8760);
 expect(saved[0].summary_result.shading_energy_loss_wh).toBeGreaterThan(0);
 expect(saved[0].summary_result.shading_energy_loss_basis.scope).toBe("geometric_near_shading_only");
 const deletion={operations:[{operation_id:"delete-field",operation_type:"delete_explicit_field",pv_field_id:"tables"},{operation_id:"delete-mesh",operation_type:"delete_mesh",obstacle_id:"stepped"}]};
 const beforeDelete=await (await request.get(url)).json();const deletePreview=await request.post(url+"/scene/geometry",{data:{...deletion,dry_run:true}});expect(deletePreview.ok()).toBe(true);expect((await deletePreview.json()).string_ids).toEqual(ids);
 expect((await request.post(url+"/scene/geometry",{data:deletion})).status()).toBe(422);expect(await (await request.get(url)).json()).toEqual(beforeDelete);
 const removed=await request.post(url+"/scene/geometry",{data:{...deletion,discard_dependent_strings:true}});expect(removed.ok()).toBe(true);const after=await removed.json();expect(after.bundle.scene.module_instances).toEqual([]);expect(after.bundle.scene.obstacles).toEqual([]);expect(after.bundle.electrical_design.strings).toEqual([]);expect(after.bundle.simulation_runs).toEqual(beforeDelete.bundle.simulation_runs);expect(errors).toEqual([]);
});
