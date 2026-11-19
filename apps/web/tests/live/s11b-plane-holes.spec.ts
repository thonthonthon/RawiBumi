import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import type { ProjectView } from '../../src/types';
const API=process.env.RAWIBUMI_API;
if(!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(':8000'))throw new Error('S11b requires a checked-free test-only API, never a user store or port 8000.');
const url=(id:string)=>`${API}/api/projects/${id}`;
async function view(request:APIRequestContext,id:string):Promise<ProjectView>{const r=await request.get(url(id));expect(r.ok()).toBe(true);return r.json();}
async function create(request:APIRequestContext,suffix:string){const name=`S11b ${suffix} ${Date.now()}`;const r=await request.post(`${API}/api/projects`,{data:{name,latitude_deg:-6.2,longitude_deg:106.8,timezone:'Asia/Jakarta',workspace_mode:'blank_engineering_plane'}});expect(r.ok()).toBe(true);const id=(await r.json()).bundle.project.project_id as string;const roof=await request.post(url(id)+'/surfaces/rectangle',{data:{name:'S11b roof',width_m:20,height_m:10,base_elevation_m:6.1}});expect(roof.ok()).toBe(true);const sid=(await roof.json()).bundle.scene.surfaces[0].surface_id as string;return{id,name,sid};}
async function open(page:Page,name:string){await page.goto('/');await page.locator('.start__row',{hasText:name}).click();await expect(page.locator('.rail')).toBeVisible();await page.keyboard.press('Alt+3');await expect(page.locator('.toollist')).toBeVisible();await page.locator('.taskpanel .layer__name',{hasText:'S11b roof'}).click();}
async function state(page:Page){return page.evaluate(async()=>(await import('/src/state/store.tsx')).uiStore.getState().state);}
async function settle(page:Page){await expect.poll(async()=>(await state(page)).busy,{timeout:30_000}).toBeNull();}
async function typed(page:Page,text:string){await page.keyboard.type(text);await expect(page.locator('.plan__typed')).toBeVisible();await page.keyboard.press('Enter');await expect(page.locator('.plan__typed')).toBeHidden();}
async function drawHole(page:Page){await page.keyboard.press('h');for(const p of ['3,3','5,3','5,5','3,5'])await typed(page,p);await page.keyboard.press('Enter');}
async function fill(page:Page){await page.keyboard.press('Alt+4');const button=page.locator('.taskpanel').getByRole('button',{name:'Apply fill',exact:true});await expect(button).toBeEnabled();const saving=page.waitForResponse(r=>r.url().endsWith('/pv-fields') && r.request().method()==='POST');await button.click();expect((await saving).ok()).toBe(true);await settle(page);await expect(page.locator('.toasts')).not.toContainText('error');}

test('draw hole, fill around it, then edge and datum planes preserve XY and match actual engine module z',async({page,request})=>{
 const {id,name,sid}=await create(request,'plane');await open(page,name);await drawHole(page);
 await expect.poll(async()=>(await view(request,id)).bundle.scene.surfaces[0].boundary_2d?.holes.length).toBe(1);await settle(page);await fill(page);
 let before=await view(request,id);expect(before.bundle.scene.module_instances.length).toBeGreaterThan(0);
 const gap=before.bundle.scene.pv_fields[0].setback_configuration!.perimeter_setback_m!;
 for(const feature of before.scene_view.local_features.filter(f=>f.category==='module')){
  // All fixture modules have azimuth zero: independent axis-aligned rectangle oracle.
  const xs=feature.polygon.map(p=>p[0]),ys=feature.polygon.map(p=>p[1]);
  const dx=Math.max(3-Math.max(...xs),Math.min(...xs)-5,0),dy=Math.max(3-Math.max(...ys),Math.min(...ys)-5,0);
  expect(dx>0 || dy>0).toBe(true);expect(Math.hypot(dx,dy)).toBeGreaterThanOrEqual(gap-1e-9);
 }
 await page.keyboard.press('Alt+3');await page.locator('.taskpanel .layer__name',{hasText:'S11b roof'}).click();
 const inspector=page.locator('.inspectorpane'),mode=inspector.getByLabel(/Plane definition/);
 for(const selection of ['edge_tilt','datum_tilt_azimuth']){
  before=await view(request,id);await mode.selectOption(selection);await settle(page);
  if(selection==='datum_tilt_azimuth'){await inspector.getByLabel('Height at the reference point').fill('9.5');await settle(page);await inspector.getByLabel('Downslope azimuth').fill('140');await settle(page);}
  const after=await view(request,id);const old=before.bundle.scene.module_instances as unknown as Array<{module_instance_id:string;transform:Record<string,number>}>;
  const modules=after.bundle.scene.module_instances as unknown as Array<{module_instance_id:string;transform:Record<string,number>}>;
  const z=await page.evaluate(async({sid,modules})=>{const {planeZ}=await import('/src/geometry.ts');const s=(await import('/src/state/store.tsx')).uiStore.getState().state,e=s.entities.find(e=>e.id===sid)!;return modules.map(m=>planeZ(e.polygon,e.plane,[m.transform.position_x_m,m.transform.position_y_m])!);},{sid,modules});
  expect(modules.map(m=>m.module_instance_id)).toEqual(old.map(m=>m.module_instance_id));
  for(let i=0;i<modules.length;i++){expect(modules[i].transform.position_x_m).toBe(old[i].transform.position_x_m);expect(modules[i].transform.position_y_m).toBe(old[i].transform.position_y_m);expect(Math.abs(modules[i].transform.position_z_m-z[i]-after.bundle.scene.pv_fields[0].mounting_height_m!)).toBeLessThanOrEqual(1e-9);}
  expect((await state(page)).entities.find(e=>e.id===sid)).toMatchObject({modified:false,pending:[]});
  const readiness=await request.get(url(id)+'/execution-readiness');expect((await readiness.json()).findings.some((f:{rule_id:string})=>f.rule_id==='SCENE_PV_FIELD_LAYOUT_STALE')).toBe(true);
 }
});

test('hole on strung roof previews affected strings, Cancel preserves storage and confirmation refills once',async({page,request})=>{
 const {id,name}=await create(request,'hosted');await open(page,name);await fill(page);
 const strings=await request.post(url(id)+'/strings',{data:{string_length:6,allow_shorter_remainder:true}});expect(strings.ok()).toBe(true);
 await open(page,name);const before=await view(request,id);await drawHole(page);
 const dialog=page.getByRole('alertdialog',{name:'Roof carries PV fields',exact:true});await expect(dialog).toBeVisible();await expect(dialog).toContainText('Modules:');await expect(dialog).toContainText('STC power:');const affected=await page.evaluate(async()=>(await import('/src/state/history.ts')).dependentFields.getState().pending!.fields.flatMap(f=>f.string_ids));expect(affected.length).toBeGreaterThan(0);for(const string of affected)await expect(dialog).toContainText(string);
 expect(await view(request,id)).toEqual(before);await dialog.getByRole('button',{name:'Cancel',exact:true}).click();await expect(dialog).toBeHidden();expect(await view(request,id)).toEqual(before);
 await drawHole(page);await expect(dialog).toBeVisible();await dialog.getByRole('button',{name:'Confirm roof change',exact:true}).click();await expect(dialog).toBeHidden();await settle(page);
 const after=await view(request,id);expect(after.bundle.scene.surfaces[0].boundary_2d?.holes.length).toBe(1);expect(after.bundle.scene.module_instances.length).toBeLessThan(before.bundle.scene.module_instances.length);expect(after.bundle.electrical_design.strings.map(s=>s.string_id).sort()).toEqual(before.bundle.electrical_design.strings.filter(s=>!affected.includes(s.string_id)).map(s=>s.string_id).sort());
 const readiness=await request.get(url(id)+'/execution-readiness');expect((await readiness.json()).findings.some((f:{rule_id:string})=>f.rule_id==='SCENE_MODULE_OVER_HOLE')).toBe(false);
});
