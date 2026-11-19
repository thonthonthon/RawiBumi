import { expect,test,type APIRequestContext,type Page } from "@playwright/test";
import type {ProjectView} from "../../src/types";
import type {Vec2} from "../../src/geometry";
const API=process.env.RAWIBUMI_API;
if(!API||!/^http:\/\/127\.0\.0\.1:\d+$/.test(API)||API.endsWith(":8000"))throw new Error("RF1 requires the isolated test API on a checked-free port, never var/projects.");
const url=(id:string)=>`${API}/api/projects/${id}`;
async function view(request:APIRequestContext,id:string):Promise<ProjectView>{const r=await request.get(url(id));expect(r.ok()).toBe(true);return r.json();}
async function setup(request:APIRequestContext){
 const name=`RF1 ${Date.now()} ${Math.random()}`;const response=await request.post(`${API}/api/projects`,{data:{name,latitude_deg:-6.2,longitude_deg:106.8,timezone:"Asia/Jakarta",workspace_mode:"blank_engineering_plane"}});expect(response.ok()).toBe(true);
 const id:string=(await response.json()).bundle.project.project_id;
 for(const [roof,x] of [["Roof 1",0],["Roof 2",20]] as const)expect((await request.post(url(id)+"/surfaces/rectangle",{data:{name:roof,origin_x_m:x,origin_y_m:0,width_m:12,height_m:10,base_elevation_m:6}})).ok()).toBe(true);
 return{id,name};
}
async function makeStrings(request:APIRequestContext,id:string){
 for(const field of (await view(request,id)).bundle.scene.pv_fields)
  expect((await request.post(url(id)+"/strings",{data:{pv_field_id:field.pv_field_id,string_length:6,allow_shorter_remainder:true}})).ok()).toBe(true);
}
async function state(page:Page){return page.evaluate(async()=>(await import("/src/state/store.tsx")).uiStore.getState().state);}
async function open(page:Page,name:string){await page.goto("/");await page.locator(".start__row",{hasText:name}).click();await expect(page.locator(".rail")).toBeVisible();await page.keyboard.press("Alt+4");}
async function point(page:Page,p:Vec2):Promise<Vec2>{return page.evaluate(([x,y])=>{
 const r=document.querySelector<HTMLCanvasElement>(".plan__canvas")!.getBoundingClientRect(),bar=document.querySelector<HTMLElement>(".plan__scalebar")!;
 const scale=parseFloat(bar.style.width)/parseFloat(bar.parentElement!.querySelector("span")!.textContent!);
 return[r.left+r.width/2+(x-16)*scale,r.top+r.height/2-(y-5)*scale];
},p);}
function own(v:ProjectView,field:string){const modules=v.bundle.scene.module_instances.filter(m=>m.pv_field_id===field),ids=new Set(modules.map(m=>m.module_instance_id));return {field:v.bundle.scene.pv_fields.find(f=>f.pv_field_id===field),modules,strings:v.bundle.electrical_design.strings.filter(s=>s.module_instance_ids.some(mid=>ids.has(mid)))};}
function patchResponse(page:Page,field:string,dry:boolean){return page.waitForResponse(r=>r.request().method()==="PATCH"&&r.url().endsWith('/pv-fields/'+field)&&!!r.request().postDataJSON().dry_run===dry);}

test("two roofs fill from canvas/dropdown targets and each refill leaves the other field byte-identical",async({page,request})=>{
 const{id,name}=await setup(request);await open(page,name);const p=page.locator(".taskpanel");
 await expect(p.getByLabel("Field name")).toHaveValue("Roof 1 array");
 const created1=page.waitForResponse(r=>r.request().method()==="POST"&&r.url().endsWith("/pv-fields"));
 await p.getByRole("button",{name:"Apply fill",exact:true}).click();expect((await created1).status()).toBe(200);
 await expect(p.locator(".card-row",{hasText:"Roof 1 array"})).toBeVisible();const first=(await view(request,id)).bundle.scene.pv_fields[0].pv_field_id;
 await page.keyboard.press("Alt+3");await page.mouse.click(...await point(page,[31.9,9.9]));await page.keyboard.press("Alt+4");
 const roof2=(await view(request,id)).bundle.scene.surfaces[1].surface_id;await expect(p.getByLabel("Support surface")).toHaveValue(roof2);
 await expect(p.getByLabel("Field name")).toHaveValue("Roof 2 array");
 const created2=page.waitForResponse(r=>r.request().method()==="POST"&&r.url().endsWith("/pv-fields"));
 await p.getByRole("button",{name:"Apply fill",exact:true}).click();const filled2=await created2;expect(filled2.status()).toBe(200);expect(filled2.request().postDataJSON().support_surface_id).toBe(roof2);
 await expect(p.locator(".card-row")).toHaveCount(2);
 let before=await view(request,id);const second=before.bundle.scene.pv_fields.find(f=>f.support_surface_id===roof2)!.pv_field_id;
 await makeStrings(request,id);await open(page,name);
 for(const [target,other,tilt] of [[first,second,15],[second,first,20]] as const){
  before=await view(request,id);const untouched=JSON.stringify(own(before,other)),field=before.bundle.scene.pv_fields.find(f=>f.pv_field_id===target)!;
  await p.getByLabel("Support surface").selectOption(field.support_surface_id);await p.getByLabel("Tilt").fill(String(tilt));
  const preview=patchResponse(page,target,true);await p.getByRole("button",{name:"Apply re-fill",exact:true}).click();expect((await preview).status()).toBe(200);
  const dialog=page.getByRole("alertdialog",{name:"Preview re-fill",exact:true});await expect(dialog).toContainText(field.name);
  const commit=patchResponse(page,target,false);await dialog.getByRole("button",{name:"Confirm re-fill",exact:true}).click();expect((await commit).status()).toBe(200);await expect(dialog).toBeHidden();
  const after=await view(request,id);expect(JSON.stringify(own(after,other))).toBe(untouched);expect(own(after,target).field!.tilt_deg).toBe(tilt);
  await expect(p.getByLabel("Support surface")).toBeEnabled();await expect(p.getByRole("combobox",{name:"Module",exact:true})).toBeEnabled();
  await expect.poll(async()=>(await state(page)).forms['layout.fill'].fieldId).toBeNull();
 }
});

test("module change previews both models and whole strings, confirms the new pinned revision on only its roof",async({page,request})=>{
 const{id,name}=await setup(request);let v=await view(request,id);const primary=v.catalog.modules.find(m=>m.simulation_ready)??v.catalog.modules[0];const next=v.catalog.modules.find(m=>m.revision_id!==primary.revision_id);expect(next,'RF1 needs both real test-catalogue modules').toBeTruthy();
 for(const surface of v.bundle.scene.surfaces)expect((await request.post(url(id)+"/pv-fields",{data:{name:surface.name+' array',support_surface_id:surface.surface_id,module_definition_revision_id:primary.revision_id,tilt_deg:10,row_pitch_m:2.6,perimeter_setback_m:.3,obstacle_setback_m:.3}})).ok()).toBe(true);
 await makeStrings(request,id);v=await view(request,id);
 const [field,other]=v.bundle.scene.pv_fields;const untouched=JSON.stringify(own(v,other.pv_field_id)),strings=own(v,field.pv_field_id).strings.map(s=>s.string_id).sort();expect(strings.length).toBeGreaterThan(0);
 await open(page,name);const p=page.locator(".taskpanel");await p.getByLabel("Support surface").selectOption(field.support_surface_id);
 await p.getByRole("combobox",{name:"Module",exact:true}).selectOption(next!.revision_id);
 const preview=patchResponse(page,field.pv_field_id,true);await p.getByRole("button",{name:"Apply re-fill",exact:true}).click();const response=await preview;expect(response.status()).toBe(200);const impact=await response.json();expect(impact.string_ids).toEqual(strings);expect(response.request().postDataJSON()).not.toHaveProperty('discard_dependent_strings');
 const dialog=page.getByRole("alertdialog",{name:"Preview re-fill",exact:true});await expect(dialog).toContainText(`Module: ${primary.model} → ${next!.model}`);for(const string of strings)await expect(dialog).toContainText(string);
 const commit=patchResponse(page,field.pv_field_id,false);await dialog.getByRole("button",{name:"Confirm re-fill",exact:true}).click();const saved=await commit;expect(saved.status()).toBe(200);expect(saved.request().postDataJSON().discard_dependent_strings).toBe(true);await expect(dialog).toBeHidden();
 const after=await view(request,id);const changed=own(after,field.pv_field_id);expect(changed.field!.module_definition_revision_id).toBe(next!.revision_id);expect(changed.modules.length).toBeGreaterThan(0);
 for(const module of changed.modules as unknown as Array<{module_definition_revision_id:string}>)expect(module.module_definition_revision_id).toBe(next!.revision_id);
 expect((after.bundle as unknown as {pinned_components:{modules:Record<string,unknown>}}).pinned_components.modules).toHaveProperty(next!.revision_id);expect(changed.strings).toEqual([]);expect(JSON.stringify(own(after,other.pv_field_id))).toBe(untouched);
});
