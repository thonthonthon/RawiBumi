import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { ModuleFillPreview, ProjectView } from "../../src/types";
import type { Vec2 } from "../../src/geometry";
const API=process.env.RAWIBUMI_API;
if(!API||!/^http:\/\/127\.0\.0\.1:\d+$/.test(API)||API.endsWith(":8000"))throw new Error("S13c needs the checked-free isolated test API, never var/projects.");
const url=(id:string)=>`${API}/api/projects/${id}`;
async function view(request:APIRequestContext,id:string):Promise<ProjectView>{const r=await request.get(url(id));expect(r.ok()).toBe(true);return r.json();}
type Placement={module_instance_id:string;row_index:number;column_index:number;transform:{position_x_m:number;position_y_m:number;position_z_m:number}};
const modules=(v:ProjectView)=>v.bundle.scene.module_instances as unknown as Placement[];
async function create(request:APIRequestContext,partial:boolean){
 const name=`S13c ${partial} ${Date.now()} ${Math.random()}`;
 const r=await request.post(`${API}/api/projects`,{data:{name,latitude_deg:-6.2,longitude_deg:106.8,timezone:"Asia/Jakarta",workspace_mode:"blank_engineering_plane"}});expect(r.ok()).toBe(true);
 const id:string=(await r.json()).bundle.project.project_id;
 expect((await request.post(url(id)+"/surfaces/rectangle",{data:{name:"Fill roof",width_m:20,height_m:12,base_elevation_m:6}})).ok()).toBe(true);
 const before=await view(request,id);
 expect((await request.post(url(id)+"/pv-fields",{data:{name:"Fill field",support_surface_id:before.bundle.scene.surfaces[0].surface_id,module_definition_revision_id:before.catalog.modules[0].revision_id,tilt_deg:10,row_pitch_m:3.1,perimeter_setback_m:.7,obstacle_setback_m:.3}})).ok()).toBe(true);
 const grid=modules(await view(request,id));const selected=grid.filter(m=>m.row_index<2&&m.column_index<3);
 if(partial){
  const targets=grid.filter(m=>m.row_index===2&&m.column_index<3);expect(targets).toHaveLength(3);
  expect((await request.post(url(id)+"/pv-fields/modules/commands",{data:{command:"delete_modules",module_instance_ids:targets.map(m=>m.module_instance_id)}})).ok()).toBe(true);
  const blocked=targets.find(m=>m.column_index===1)!.transform;
  expect((await request.post(url(id)+"/obstacles/box",{data:{name:"AHU fill",origin_x_m:blocked.position_x_m-.2,origin_y_m:blocked.position_y_m-.2,width_m:.4,depth_m:.4,base_elevation_m:6,height_m:2}})).ok()).toBe(true);
 }
 expect((await request.post(url(id)+"/strings",{data:{string_length:6,allow_shorter_remainder:true}})).ok()).toBe(true);
 return {id,name,grid,selected};
}
async function state(page:Page){return page.evaluate(async()=>(await import("/src/state/store.tsx")).uiStore.getState().state);}
async function open(page:Page,name:string){await page.goto("/");await page.locator(".start__row",{hasText:name}).click();await expect(page.locator(".rail")).toBeVisible();await page.keyboard.press("Alt+4");await expect.poll(async()=>(await state(page)).busy).toBeNull();}
async function point(page:Page,p:Vec2):Promise<Vec2>{return page.evaluate(([x,y])=>{
 const r=document.querySelector<HTMLCanvasElement>(".plan__canvas")!.getBoundingClientRect(),bar=document.querySelector<HTMLElement>(".plan__scalebar")!;
 const scale=parseFloat(bar.style.width)/parseFloat(bar.parentElement!.querySelector("span")!.textContent!);
 return[r.left+r.width/2+(x-10)*scale,r.top+r.height/2-(y-6)*scale];
},p);}
async function select(page:Page,chosen:Placement[]){await page.keyboard.press("Escape");for(let i=0;i<chosen.length;i++){
 if(i)await page.keyboard.down("Shift");const t=chosen[i].transform;await page.mouse.click(...await point(page,[t.position_x_m,t.position_y_m]));if(i)await page.keyboard.up("Shift");
}await expect.poll(async()=>(await state(page)).selection.slice().sort()).toEqual(chosen.map(m=>m.module_instance_id).sort());}
async function drag(page:Page,chosen:Placement[],dy:number){const t=chosen[0].transform;await page.mouse.move(...await point(page,[t.position_x_m,t.position_y_m]));await page.mouse.down();await page.keyboard.down("Shift");await page.mouse.move(...await point(page,[t.position_x_m,t.position_y_m+dy]),{steps:6});await page.mouse.up();await page.keyboard.up("Shift");}
const dialog=(page:Page)=>page.getByRole("alertdialog",{name:"These modules don't fit exactly there. Fit into this space?"});

test("partial drop previews five of six slots, Cancel is read-only, Confirm keeps slot transforms and deletes only affected strings",async({page,request})=>{
 const {id,name,grid,selected}=await create(request,true);const before=await view(request,id);await open(page,name);await select(page,selected);
 const previews:ModuleFillPreview[]=[];let commits=0;
 page.on("response",async r=>{if(r.url().endsWith("/pv-fields/modules/commands")&&r.request().method()==="POST"){
  const body=r.request().postDataJSON();if(body.on_conflict==="fill"&&body.dry_run&&r.status()===200)previews.push(await r.json());if(body.on_conflict==="fill"&&!body.dry_run)commits++;
 }});
 await drag(page,selected,3.1);await expect(dialog(page)).toContainText("5 of 6 placed, 1 removed");await expect.poll(()=>previews.length).toBe(1);
 const preview=previews[0];const order=(a:Placement,b:Placement)=>Math.round(b.transform.position_y_m*1000)-Math.round(a.transform.position_y_m*1000)||Math.round(a.transform.position_x_m*1000)-Math.round(b.transform.position_x_m*1000);
 const original=[...selected].sort(order);expect(preview.placed_ids).toEqual(original.slice(0,5).map(m=>m.module_instance_id));expect(preview.removed_ids).toEqual([original[5].module_instance_id]);
 const strings=before.bundle.electrical_design.strings.filter(s=>s.module_instance_ids.includes(original[5].module_instance_id)).map(s=>s.string_id).sort();expect(preview.string_ids).toEqual(strings);
 for(const sid of strings)await expect(dialog(page)).toContainText(sid);
 await expect(dialog(page)).toContainText("module would overlap obstacle AHU fill");
 await dialog(page).getByRole("button",{name:"Cancel",exact:true}).click();await expect(dialog(page)).toBeHidden();expect(commits).toBe(0);expect(await view(request,id)).toEqual(before);
 await drag(page,selected,3.1);await expect(dialog(page)).toContainText("5 of 6 placed, 1 removed");
 const saved=page.waitForResponse(r=>r.url().endsWith("/pv-fields/modules/commands")&&r.request().postDataJSON().on_conflict==="fill"&&!r.request().postDataJSON().dry_run);
 await dialog(page).getByRole("button",{name:"Confirm fill",exact:true}).click();const response=await saved;expect(response.status()).toBe(200);expect(response.request().postDataJSON().discard_dependent_strings).toBe(true);
 await expect(dialog(page)).toBeHidden();const after=await view(request,id);
 const slots=grid.filter(m=>(m.row_index===1||m.row_index===2)&&m.column_index<3&&!(m.row_index===2&&m.column_index===1)).sort(order);
 for(let i=0;i<5;i++)expect(modules(after).find(m=>m.module_instance_id===original[i].module_instance_id)!.transform).toEqual(slots[i].transform);
 expect(modules(after).some(m=>m.module_instance_id===original[5].module_instance_id)).toBe(false);
 expect(after.bundle.electrical_design.strings).toEqual(before.bundle.electrical_design.strings.filter(s=>!strings.includes(s.string_id)));
 await expect.poll(async()=>(await state(page)).selection).toEqual(preview.placed_ids);
});

test("fully occupied target has plain reasons and no Confirm",async({page,request})=>{
 const {id,name,grid}=await create(request,false);const chosen=[grid.find(m=>m.row_index===0&&m.column_index===0)!];const before=await view(request,id);
 await open(page,name);await select(page,chosen);await drag(page,chosen,6.2);
 await expect(dialog(page)).toContainText("No modules fit in this space.");await expect(dialog(page).getByRole("button",{name:"Confirm fill",exact:true})).toHaveCount(0);
 await dialog(page).getByRole("button",{name:"Cancel",exact:true}).click();expect(await view(request,id)).toEqual(before);
});
