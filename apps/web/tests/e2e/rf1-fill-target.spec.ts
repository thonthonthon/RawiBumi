import { expect, test, type Page } from "@playwright/test";
import type { Vec2 } from "../../src/geometry";
async function state(page:Page){return page.evaluate(async()=>(await import("/src/state/store.tsx")).uiStore.getState().state);}
async function open(page:Page,withField=false){
 await page.goto("/");await page.locator(".start__row").first().click();await expect(page.locator(".rail")).toBeVisible();
 return page.evaluate(async(withField)=>{
  const {mockApi}=await import("/src/demo/mockApi.ts");const {uiStore}=await import("/src/state/store.tsx");
  let view=await mockApi.addSurface("demo-project",{name:"Roof B",origin_x_m:60,origin_y_m:0,width_m:12,height_m:10,base_elevation_m:6,surface_type:"flat_roof"});
  const surface=view.bundle.scene.surfaces.at(-1)!.surface_id;
  if(withField)view=await mockApi.createPvField("demo-project",{name:"Roof B array",support_surface_id:surface,module_definition_revision_id:"mod-demo-550",orientation:"portrait",azimuth_deg:0,tilt_deg:10,module_gap_x_m:.02,module_gap_y_m:.02,row_pitch_m:3.1,mounting_height_m:.2,perimeter_setback_m:.3,obstacle_setback_m:.3});
  uiStore.getState().dispatch({type:"setView",view});return surface;
 },withField);
}
async function point(page:Page,p:Vec2):Promise<Vec2>{return page.evaluate(([x,y])=>(window as unknown as {__rawibumiPlan:{toPage(x:number,y:number):Vec2}}).__rawibumiPlan.toPage(x,y),p);}

test("canvas roof 2 selection targets its new fill and its unique roof-derived name",async({page})=>{
 const roof=await open(page);await page.keyboard.press("Alt+3");await page.keyboard.press("Escape");await page.keyboard.press("z");
 await page.mouse.click(...await point(page,[71.9,9.9]));await expect.poll(async()=>(await state(page)).selection).toEqual([roof]);
 await page.keyboard.press("Alt+4");const p=page.locator(".taskpanel");
 await expect(p.getByLabel("Support surface")).toHaveValue(roof);await expect(p.getByLabel("Field name")).toHaveValue("Roof B array");
 await p.getByLabel("Field name").fill("My array");await p.getByLabel("Support surface").selectOption(roof);
 await expect(p.getByLabel("Field name")).toHaveValue("My array");
 await expect(p.getByLabel("Support surface")).toBeEnabled();await expect(p.getByRole("combobox",{name:"Module",exact:true})).toBeEnabled();
});

test("refill roof 1 then choose roof 2: success clears the mode and each preview names its own roof",async({page})=>{
 const roof=await open(page,true);await page.keyboard.press("Alt+4");const p=page.locator(".taskpanel");
 await expect(p).toContainText("Roof A already has 'Roof A array'. Apply fill replaces its layout");
 await p.locator(".card-row",{hasText:"Roof A array"}).getByRole("button",{name:"Re-fill",exact:true}).click();await p.getByLabel("Tilt").fill("15");await p.getByRole("button",{name:"Apply re-fill",exact:true}).click();
 const dialog=page.getByRole("alertdialog",{name:"Preview re-fill",exact:true});await expect(dialog).toContainText("Roof A array on Roof A");
 await dialog.getByRole("button",{name:"Confirm re-fill",exact:true}).click();await expect(dialog).toBeHidden();
 await expect.poll(async()=>(await state(page)).forms['layout.fill'].fieldId).toBeNull();
 await expect(p.getByLabel("Support surface")).toBeEnabled();await expect(p.getByRole("combobox",{name:"Module",exact:true})).toBeEnabled();
 await p.getByLabel("Support surface").selectOption(roof);await expect(p).toContainText("Re-fill Roof B array");
 await p.getByLabel("Tilt").fill("20");await p.getByRole("button",{name:"Apply re-fill",exact:true}).click();await expect(dialog).toContainText("Roof B array on Roof B");
 await dialog.getByRole("button",{name:"Confirm re-fill",exact:true}).click();await expect(dialog).toBeHidden();
 const scene=(await state(page)).view!.bundle.scene;expect(scene.pv_fields.find(f=>f.pv_field_id==="fld-a")!.tilt_deg).toBe(15);
 expect(scene.pv_fields.find(f=>f.support_surface_id===roof)!.tilt_deg).toBe(20);
 await expect.poll(async()=>(await state(page)).forms['layout.fill'].fieldId).toBeNull();
});

test("demo module replacement gives the honest engine-only message and preserves the field",async({page})=>{
 await open(page);await page.keyboard.press("Alt+4");const p=page.locator(".taskpanel");
 await p.locator(".card-row",{hasText:"Roof A array"}).getByRole("button",{name:"Re-fill",exact:true}).click();const before=(await state(page)).view;
 await p.getByRole("combobox",{name:"Module",exact:true}).selectOption("mod-demo-610");await p.getByRole("button",{name:"Apply re-fill",exact:true}).click();
 await expect(page.locator(".toasts")).toContainText("Changing the module needs the engine");
 expect((await state(page)).view).toEqual(before);await expect(page.getByRole("alertdialog")).toHaveCount(0);
});
