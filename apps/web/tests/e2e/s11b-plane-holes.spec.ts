import { expect, test, type Page } from "@playwright/test";
async function state(page:Page){return page.evaluate(async()=>(await import('/src/state/store.tsx')).uiStore.getState().state);}
async function typed(page:Page,text:string){await page.keyboard.type(text);await expect(page.locator('.plan__typed')).toBeVisible();await page.keyboard.press('Enter');await expect(page.locator('.plan__typed')).toBeHidden();}
async function settled(page:Page){await expect.poll(async()=>(await state(page)).busy).toBeNull();}
async function point(page:Page,x:number,y:number):Promise<[number,number]>{return page.evaluate(([x,y])=>(window as unknown as {__rawibumiPlan:{toPage(x:number,y:number):[number,number]}}).__rawibumiPlan.toPage(x,y),[x,y]);}
async function openRoof(page:Page){await page.goto('/');await page.locator('.start__row').first().click();await expect(page.locator('.rail')).toBeVisible();await page.keyboard.press('Alt+3');await expect(page.locator('.toollist')).toBeVisible();await page.keyboard.press('p');for(const p of ['2,-14','10,-14','10,-6','2,-6'])await typed(page,p);await page.keyboard.press('Enter');await expect(page.locator('.inspectorpane')).toContainText('Surface 2');await settled(page);return (await state(page)).selection[0];}
async function hole(page:Page){await page.keyboard.press('h');for(const p of ['4,-12','6,-12','6,-10','4,-10'])await typed(page,p);await page.keyboard.press('Enter');await settled(page);}
test('flat, reference-edge and datum planes persist without local drafts',async({page})=>{
 const id=await openRoof(page),inspector=page.locator('.inspectorpane');
 const mode=inspector.getByLabel(/Plane definition/);
 await mode.selectOption('edge_tilt');await settled(page);await expect(mode).toHaveValue('edge_tilt');
 await inspector.getByRole('spinbutton',{name:/^Tilt/}).fill('12');await settled(page);
 let s=await state(page);let surface=s.view!.bundle.scene.surfaces.find(x=>x.surface_id===id)!;expect(surface.slope_deg).toBe(12);expect(surface.elevation_reference?.mode).toBe('explicit_xy');
 await mode.selectOption('datum_tilt_azimuth');await settled(page);await expect(mode).toHaveValue('datum_tilt_azimuth');
 await inspector.getByLabel('Height at the reference point').fill('9.25');await settled(page);await inspector.getByLabel('Downslope azimuth').fill('130');await settled(page);
 s=await state(page);surface=s.view!.bundle.scene.surfaces.find(x=>x.surface_id===id)!;expect(surface.base_elevation_m).toBe(9.25);expect(surface.azimuth_deg).toBe(130);
 expect(s.entities.find(x=>x.id===id)).toMatchObject({modified:false,pending:[],plane:{mode:'datum_tilt_azimuth'}});
 await mode.selectOption('flat');await settled(page);s=await state(page);expect(s.view!.bundle.scene.surfaces.find(x=>x.surface_id===id)!.slope_deg).toBe(0);
 await expect(inspector).not.toContainText('Not wired');await expect(inspector).not.toContainText('engine + local edits');
});
test('hole creation, ring insertion/deletion/edge drag and whole-hole removal persist',async({page})=>{
 const id=await openRoof(page);await hole(page);
 const ring=async()=>(await state(page)).view!.bundle.scene.surfaces.find(x=>x.surface_id===id)!.boundary_2d!.holes[0];
 await expect.poll(async()=> (await ring())?.length).toBe(4);
 await page.mouse.dblclick(...await point(page,5,-12));await expect.poll(async()=>(await ring()).length).toBe(5);await settled(page);
 await page.keyboard.down('Alt');await page.mouse.click(...await point(page,5,-12));await page.keyboard.up('Alt');await expect.poll(async()=>(await ring()).length).toBe(4);await settled(page);
 await page.keyboard.down('Alt');await page.mouse.move(...await point(page,5,-10));await page.mouse.down();await page.mouse.move(...await point(page,5,-9.5),{steps:5});await page.mouse.up();await page.keyboard.up('Alt');
 await expect.poll(async()=>(await ring())[2][1]).toBeCloseTo(-9.5,1);await settled(page);
 expect((await state(page)).entities.find(x=>x.id===id)).toMatchObject({modified:false,pending:[]});
 await page.getByRole('button',{name:'Remove hole 1',exact:true}).click();await expect.poll(async()=>(await state(page)).view!.bundle.scene.surfaces.find(x=>x.surface_id===id)!.boundary_2d!.holes.length).toBe(0);
});
