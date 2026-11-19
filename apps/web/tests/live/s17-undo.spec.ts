import { expect,test as base,type APIRequestContext,type Page } from "@playwright/test";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { readFileSync,mkdirSync,mkdtempSync,rmSync } from "node:fs";
import path from "node:path";
let API=process.env.RAWIBUMI_API;
if(!API||!/^http:\/\/127\.0\.0\.1:\d+$/.test(API)||API.endsWith(':8000'))throw new Error('S17 requires the isolated API, never a user store.');
const ROOT=path.resolve(process.cwd(),'../..');

// Session history and weather barriers run on a disposable real service.
// No mocks, product store, accounts or browser-history hooks.
const test=base.extend<{}, {historyApi:string}>({
 historyApi:[async({},use)=>{
  mkdirSync(path.join(ROOT,'tmp'),{recursive:true});
  const directory=mkdtempSync(path.join(ROOT,'tmp','s17-library-live-'));
  const script=`import runpy
from pathlib import Path
runpy.run_path("apps/web/scripts/serve-live-test-api.py",run_name="s17_test_catalog")
from apps.api.server import create_app
import uvicorn
uvicorn.run(create_app(store_root=Path(${JSON.stringify(directory)})/"projects",library_root=Path(${JSON.stringify(directory)})/"component-library"),host="127.0.0.1",port=0,timeout_keep_alive=75)
`;
  const child=spawn(path.join(ROOT,'.venv/bin/python'),['-c',script],{cwd:ROOT,stdio:['ignore','pipe','pipe']});
  let logs='';
  try{
   API=await new Promise<string>((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error(`S17 isolated API startup timed out: ${logs}`)),20000);
    const data=(chunk:Buffer)=>{logs+=chunk.toString();const address=logs.match(/Uvicorn running on (http:\/\/127\.0\.0\.1:\d+)/);if(address){clearTimeout(timer);resolve(address[1]);}};
    child.stdout.on('data',data);child.stderr.on('data',data);
    child.once('error',error=>{clearTimeout(timer);reject(error);});
    child.once('exit',code=>{clearTimeout(timer);reject(new Error(`S17 isolated API exited ${code}: ${logs}`));});
   });
   await use(API);
  }finally{
   if(child.exitCode===null&&child.signalCode===null){const closed=once(child,'exit');child.kill('SIGTERM');await closed;}
   rmSync(directory,{recursive:true,force:true});
  }
 },{scope:'worker',auto:true}],
 page:async({page,historyApi},use)=>{
  await page.route('**/api/**',async route=>{
   const source=new URL(route.request().url());
   const response=await route.fetch({url:historyApi+source.pathname+source.search});
   await route.fulfill({response});
  });
  await use(page);
 }
});

type View=import("../../src/types").ProjectView;
async function stored(request:APIRequestContext,id:string):Promise<View>{const r=await request.get(`${API}/api/projects/${id}`);expect(r.ok()).toBe(true);return r.json();}
function design(view:View){
 const b=structuredClone(view.bundle) as unknown as Record<string,Record<string,unknown>>;
 const omit=(value:Record<string,unknown>,keys:string[])=>Object.fromEntries(Object.entries(value).filter(([k])=>!keys.includes(k)));
 return {...Object.fromEntries(["pinned_components","pinned_electrical_shading_assets","electrical_shading_selections","loss_settings","optics_thermal_settings","shading_accuracy","weather_selection"].filter(k=>k in b).map(k=>[k,b[k]])),
  project:omit(b.project,["project_revision"]),scene:omit(b.scene,["revision_id","revision_number","supersedes_revision_id","created_at","created_by","status","change_summary"]),
  electrical:omit(b.electrical_design,["electrical_revision_id","revision_number","supersedes_revision_id","supersedes_electrical_revision_id","project_revision_id","created_at","created_by","status","change_summary"])};
}
async function setup(page:Page,request:APIRequestContext){
 const name=`S17 ${Date.now()} ${Math.random()}`;
 const created=await request.post(`${API}/api/projects`,{data:{name,latitude_deg:-6.2,longitude_deg:106.8,timezone:"Asia/Jakarta",workspace_mode:"blank_engineering_plane"}});expect(created.status()).toBe(201);
 const id=(await created.json()).bundle.project.project_id;
 for(const [suffix,data] of [["/surfaces/rectangle",{name:"History roof",width_m:12,height_m:8,base_elevation_m:6}],
  ["/surfaces/rectangle",{name:"Free roof",origin_x_m:30,width_m:6,height_m:6,base_elevation_m:0}],
  ["/inverters",{name:"INV",inverter_definition_revision_id:"inv-rawibumi-ref-150k-r1"}]] as const){expect((await request.post(`${API}/api/projects/${id}${suffix}`,{data})).ok()).toBe(true);}
 const v=await stored(request,id);
 await page.goto("/");await page.locator(".start__row",{hasText:name}).click();await expect(page.locator(".rail")).toBeVisible();
 return {id,name,roof:v.bundle.scene.surfaces[0].surface_id,free:v.bundle.scene.surfaces[1].surface_id};
}
async function settled(page:Page){await expect.poll(()=>page.evaluate(async()=> (await import(/* @vite-ignore */ "/src/state/store.tsx")).uiStore.getState().state.busy)).toBeNull();}
async function edit(page:Page,id:string,kind:string){
 // Exercise the real client and the same history wrapper used by design tools.
 // Undo/redo themselves always go through the visible buttons and keyboard.
 await page.evaluate(async({id,kind})=>{
  const {engine}=await import(/* @vite-ignore */ "/src/client.ts");
  const {engineCommand}=await import(/* @vite-ignore */ "/src/state/history.ts");
  const {uiStore}=await import(/* @vite-ignore */ "/src/state/store.tsx");
  const v=uiStore.getState().state.view!;const roof=v.bundle.scene.surfaces[0].surface_id,free=v.bundle.scene.surfaces[1].surface_id;
  const f=v.bundle.scene.pv_fields[0];
  const command=(command_type:string,parameters:Record<string,unknown>)=>({command_id:`s17-${Date.now()}`,command_type,target_entity_ids:[free],parameters});
  await engineCommand(kind,async()=>{
   if(kind==="move")return engine.moveSceneEntity(id,{entity_id:free,dx_m:1,dy_m:0});
   if(kind==="delete")return engine.sceneCommand(id,command("delete",{}));
   if(kind==="vertex delete")return engine.sceneCommand(id,command("delete_vertex",{vertex_index:0}));
   if(kind==="fill")return engine.createPvField(id,{name:"History array",support_surface_id:roof,module_definition_revision_id:"mod-rawibumi-ref-650-r1",orientation:"portrait",azimuth_deg:180,tilt_deg:10,module_gap_x_m:0.02,module_gap_y_m:0.02,row_pitch_m:3.2,mounting_height_m:0.2,perimeter_setback_m:0.5,obstacle_setback_m:0.3});
   if(kind==="refill")return engine.updatePvField(id,f.pv_field_id,{tilt_deg:15},{discard_dependent_strings:true});
   if(kind==="strings")return engine.createStrings(id,{string_length:6,allow_shorter_remainder:true});
   if(kind==="assignment")return engine.assignStrings(id,{inverter_instance_id:v.bundle.electrical_design.inverter_instances[0].inverter_instance_id});
   return engine.updateShadingAccuracy(id,{overrides:{level:"high"}});
  });
 },{id,kind});await settled(page);
}
async function roundtrip(page:Page,request:APIRequestContext,id:string,before:View,after:View){
 for(const keyboard of [true,false]){
  for(const redo of [false,true]){
   const response=page.waitForResponse(r=>r.url().endsWith(`/projects/${id}/${redo?"redo":"undo"}`)&&r.request().method()==="POST");
   if(keyboard){await page.getByRole("button",{name:redo?"Redo":"Undo",exact:true}).focus();await page.keyboard.press(redo?"Control+Shift+z":"Control+z");}
   else await page.getByRole("button",{name:redo?"Redo":"Undo",exact:true}).click();
   expect((await response).ok()).toBe(true);await settled(page);
   expect(design(await stored(request,id))).toEqual(design(redo?after:before));
  }
 }
}
for(const kind of ["move","delete","vertex delete","fill","refill","assignment","settings"]){
 test(`${kind} restores exact design through keyboard and buttons`,async({page,request})=>{
  const {id}=await setup(page,request);
  if(kind==="refill"||kind==="assignment"){await edit(page,id,"fill");await edit(page,id,"strings");}
  const before=await stored(request,id);await edit(page,id,kind);const after=await stored(request,id);
  expect(design(after)).not.toEqual(design(before));await roundtrip(page,request,id,before,after);
 });
}
test("weather import is a barrier; two-tab rename conflicts despite the same revision",async({page,request,context})=>{
 const {id,name}=await setup(page,request);await edit(page,id,"move");
 const stale=await stored(request,id);
 const other=await context.newPage();
 await other.route("**/api/**",async route=>{const u=new URL(route.request().url());const r=await route.fetch({url:API+u.pathname+u.search});await route.fulfill({response:r});});
 await other.goto("/");await other.locator(".start__row",{hasText:name}).click();await expect(other.locator(".rail")).toBeVisible();
 await other.evaluate(async id=>{const {engine}=await import(/* @vite-ignore */ "/src/client.ts");await engine.updateProject(id,{name:"Other tab rename"});},id);
 expect((await stored(request,id)).bundle.project.project_revision).toEqual(stale.bundle.project.project_revision);
 const conflict=page.waitForResponse(r=>r.url().endsWith(`/projects/${id}/undo`));await page.getByRole("button",{name:"Undo",exact:true}).click();
 expect((await conflict).status()).toBe(409);await expect(page.locator(".toasts")).toContainText("Undo history is no longer available");
 await expect(page.getByRole("button",{name:"Undo",exact:true})).toBeDisabled();await other.close();
 const imported=await request.post(`${API}/api/projects/${id}/weather/import?filename=synthetic.csv&dry_run=false&accept_distant_location=true`,{data:readFileSync(path.join(ROOT,"tests/fixtures/weather/opensimpv_hourly.csv")),headers:{"Content-Type":"application/octet-stream"}});
 expect(imported.ok()).toBe(true);expect((await stored(request,id)).history!.past).toEqual([]);
 const refused=await request.post(`${API}/api/projects/${id}/undo`,{data:{expected_project_revision_id:stale.bundle.project.project_revision.project_revision_id,expected_entry_id:stale.history!.past.at(-1)!.entry_id}});
 expect(refused.status()).toBe(409);expect((await refused.json()).detail.reason).toBe("history_unavailable");
});
