import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { edgeNormal, offsetEdge } from "../../src/canvas/plan/edit";
import type { Vec2 } from "../../src/geometry";
import type { ProjectView, ObstacleConflictDetail } from "../../src/types";

const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("S11a requires a checked-free test-only API, never a user store or port 8000.");
const url = (id: string) => `${API}/api/projects/${id}`;
async function get(request: APIRequestContext, id: string): Promise<ProjectView> {
  const response = await request.get(url(id)); expect(response.ok()).toBe(true); return response.json();
}
async function create(request: APIRequestContext, suffix: string, withField = false) {
  const name = `S11a ${suffix} ${Date.now()}`;
  const response = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(response.ok()).toBe(true); const id = (await response.json()).bundle.project.project_id as string;
  const roof = await request.post(url(id)+"/surfaces/rectangle", { data: { name: "S11a roof", width_m: 20, height_m: 10, base_elevation_m: 6.1 } });
  expect(roof.ok()).toBe(true); const sid = (await roof.json()).bundle.scene.surfaces[0].surface_id as string;
  if (withField) {
    const catalog = await (await request.get(`${API}/api/catalog`)).json();
    const module = catalog.modules.find((m: { revision_id: string }) => m.revision_id==="mod-rawibumi-uat-550-r1") ?? catalog.modules[0];
    expect((await request.post(url(id)+"/pv-fields", { data: { name:"S11a field", support_surface_id:sid, module_definition_revision_id:module.revision_id, tilt_deg:10, row_pitch_m:3.1, perimeter_setback_m:.5, obstacle_setback_m:.3 } })).ok()).toBe(true);
  }
  return {id,name,sid};
}
async function open(page: Page, name: string) {
  await page.goto("/"); await page.locator(".start__row", {hasText:name}).click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+3"); await expect(page.locator(".toollist")).toBeVisible();
}
async function typed(page: Page, value: string) {
  await page.keyboard.type(value); await expect(page.locator(".plan__typed")).toBeVisible(); await page.keyboard.press("Enter");
  await expect(page.locator(".plan__typed")).toBeHidden();
}
async function point(page: Page, x: number, y: number): Promise<[number, number]> {
  // Each project starts on its only 20 x 10 roof; no test pans or zooms.
  return page.evaluate(([x,y]) => {
    const canvas=document.querySelector<HTMLCanvasElement>(".plan__canvas")!, box=canvas.getBoundingClientRect();
    const bar=document.querySelector<HTMLElement>(".plan__scalebar")!;
    const scale=parseFloat(bar.style.width)/parseFloat(bar.parentElement!.querySelector("span")!.textContent!);
    return [box.left+canvas.clientWidth/2+(x-10)*scale,box.top+canvas.clientHeight/2-(y-5)*scale];
  },[x,y]);
}
const ring = (view: ProjectView,id: string): Vec2[] => view.scene_view.local_features.find((f)=>f.id===id)!.polygon;
async function settled(page: Page, id?: string, expected?: Vec2[]) {
  await expect.poll(()=>page.evaluate(async ({id,expected})=>{
    const state=(await import("/src/state/store.tsx")).uiStore.getState().state;
    return !state.busy && (!id || JSON.stringify(state.entities.find((e)=>e.id===id)?.polygon)===JSON.stringify(expected));
  },{id,expected})).toBe(true);
}
function same(actual: Vec2[],expected: Vec2[]) {
  expect(actual).toHaveLength(expected.length);
  for(let i=0;i<expected.length;i++)for(let axis=0;axis<2;axis++)expect(Math.abs(actual[i][axis]-expected[i][axis])).toBeLessThanOrEqual(1e-9);
}

test("keep-out over strung modules: cancel preserves the bundle; confirmed removal matches the engine preview",async({page,request})=>{
  const {id,name}=await create(request,"keepout",true);
  expect((await request.post(url(id)+"/strings",{data:{string_length:6,allow_shorter_remainder:true}})).ok()).toBe(true);
  const before=await get(request,id), module=before.scene_view.local_features.find((f)=>f.category==="module")!;
  const x=Math.min(...module.polygon.map((p)=>p[0]))+.1,y=Math.min(...module.polygon.map((p)=>p[1]))+.1;
  await open(page,name);
  async function draw(){await page.keyboard.press("k");for(const p of [`${x},${y}`,`${x+.3},${y}`,`${x+.3},${y+.3}`])await typed(page,p);await page.keyboard.press("Enter");}
  const initial=page.waitForResponse((r)=>r.url().endsWith(`/projects/${id}/scene/commands`)&&r.request().method()==="POST");
  await draw();const refused=await initial;expect(refused.status()).toBe(422);
  const detail: ObstacleConflictDetail=(await refused.json()).detail, impact=detail.options.remove_modules;
  const dialog=page.getByRole("alertdialog",{name:"Keep-out on modules",exact:true});await expect(dialog).toBeVisible();
  expect(impact.module_count).toBeGreaterThan(0);expect(impact.string_ids.length).toBeGreaterThan(0);
  for(const string of impact.string_ids)await expect(dialog).toContainText(string);
  expect(await get(request,id)).toEqual(before);
  await dialog.getByRole("button",{name:"Cancel keep-out",exact:true}).click();await expect(dialog).toBeHidden();expect(await get(request,id)).toEqual(before);
  await draw();await expect(dialog).toBeVisible();
  const saving=page.waitForResponse((r)=>r.url().endsWith(`/projects/${id}/scene/commands`)&&r.request().postDataJSON()?.on_module_conflict==="remove_modules");
  await dialog.getByRole("button",{name:"Remove modules inside keep-out",exact:true}).click();
  const saved=await saving;expect(saved.ok()).toBe(true);await expect(dialog).toBeHidden();await settled(page);
  const finalBody=saved.request().postDataJSON();expect(finalBody.discard_dependent_strings).toBe(true);expect(finalBody).not.toHaveProperty("discard_manual_layout");
  const after=await get(request,id);
  expect(before.bundle.scene.module_instances.filter((m)=>!after.bundle.scene.module_instances.some((n)=>n.module_instance_id===m.module_instance_id)).map((m)=>m.module_instance_id).sort()).toEqual(impact.module_instance_ids);
  expect(after.bundle.electrical_design.strings).toEqual(before.bundle.electrical_design.strings.filter((s)=>!impact.string_ids.includes(s.string_id)));
  const keepout=after.bundle.scene.surfaces.find((s)=>s.surface_type==="exclusion_area")!;
  const entity=await page.evaluate(async(sid)=>(await import("/src/state/store.tsx")).uiStore.getState().state.entities.find((e)=>e.id===sid),keepout.surface_id);
  expect(entity).toMatchObject({kind:"keepout",source:"engine",modified:false,pending:[]});
});

test("free-roof insert, delete and dragged edge match the persisted engine coordinates to 1e-9",async({page,request})=>{
  const {id,name,sid}=await create(request,"vertices");await open(page,name);await page.locator(".taskpanel .layer__name",{hasText:"S11a roof"}).click();
  const original=ring(await get(request,id),sid);
  await settled(page,sid,original);
  const inserting=page.waitForResponse((r)=>r.url().endsWith(`/projects/${id}/scene/commands`)&&r.request().postDataJSON()?.command?.command_type==="insert_vertex");
  await page.mouse.dblclick(...await point(page,10,10));const inserted=await inserting;expect(inserted.ok()).toBe(true);
  const p=inserted.request().postDataJSON().command.parameters;expect(p.edge_index).toBe(2);
  const expected:Vec2[]=[...original.slice(0,3),[p.x_m,p.y_m],...original.slice(3)];
  same(ring(await get(request,id),sid),expected);await settled(page,sid,expected);
  const deleting=page.waitForResponse((r)=>r.url().endsWith(`/projects/${id}/scene/commands`)&&r.request().postDataJSON()?.command?.command_type==="delete_vertex");
  await page.keyboard.down("Alt");await page.mouse.click(...await point(page,p.x_m,p.y_m));await page.keyboard.up("Alt");
  const deleted=await deleting;expect(deleted.ok()).toBe(true);expect(deleted.request().postDataJSON().command.parameters).toEqual({vertex_index:3});
  same(ring(await get(request,id),sid),original);await settled(page,sid,original);
  const moving=page.waitForResponse((r)=>r.url().endsWith(`/projects/${id}/scene/commands`)&&r.request().postDataJSON()?.command?.command_type==="move_edge");
  await page.keyboard.down("Alt");await page.mouse.move(...await point(page,10,10));await page.mouse.down();await page.mouse.move(...await point(page,10,11.5),{steps:5});await page.mouse.up();await page.keyboard.up("Alt");
  const moved=await moving;expect(moved.ok()).toBe(true);const delta=moved.request().postDataJSON().command.parameters;expect(delta.edge_index).toBe(2);
  const normal=edgeNormal(original,2),offset=delta.dx_m*normal[0]+delta.dy_m*normal[1];expect(offset).toBeGreaterThan(0);
  const preview=offsetEdge(original,2,offset);same(ring(await get(request,id),sid),preview);await settled(page,sid,preview);
  const entity=await page.evaluate(async(sid)=>(await import("/src/state/store.tsx")).uiStore.getState().state.entities.find((e)=>e.id===sid),sid);
  expect(entity).toMatchObject({source:"engine",modified:false,pending:[]});
});

test("Inspector height raises an obstacle through the conflict dialog, then persists a lower height",async({page,request})=>{
  const {id,name}=await create(request,"height",true);let before=await get(request,id);
  const module=before.scene_view.local_features.find((f)=>f.category==="module")!;
  const x=Math.min(...module.polygon.map((p)=>p[0]))+.1,y=Math.min(...module.polygon.map((p)=>p[1]))+.1;
  expect((await request.post(url(id)+"/obstacles/box",{data:{name:"S11a low box",origin_x_m:x,origin_y_m:y,width_m:.3,depth_m:.3,base_elevation_m:0,height_m:1}})).ok()).toBe(true);
  before=await get(request,id);const oid=before.bundle.scene.obstacles[0].obstacle_id;
  await open(page,name);await page.locator(".taskpanel .layer__name",{hasText:"S11a low box"}).click();
  const height=page.locator(".inspectorpane").getByLabel("Height");
  await height.fill("7");await height.press("Enter");const dialog=page.getByRole("alertdialog",{name:"Obstacle on modules",exact:true});await expect(dialog).toBeVisible();expect(await get(request,id)).toEqual(before);
  await dialog.getByRole("button",{name:"Cancel obstacle",exact:true}).click();await expect(dialog).toBeHidden();expect(await get(request,id)).toEqual(before);
  await height.fill("7");await height.press("Enter");await expect(dialog).toBeVisible();await dialog.getByRole("button",{name:"Remove modules under obstacle",exact:true}).click();await expect(dialog).toBeHidden();await settled(page);
  expect((await get(request,id)).bundle.scene.obstacles[0].height_m).toBe(7);
  await expect(height).toBeEnabled();await height.fill("0.5");await height.press("Enter");
  await expect.poll(async()=>(await get(request,id)).bundle.scene.obstacles.find((o)=>o.obstacle_id===oid)!.height_m).toBe(.5);await settled(page);
});
