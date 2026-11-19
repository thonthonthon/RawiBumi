import { expect, test } from "@playwright/test";
const API=process.env.RAWIBUMI_API;
if(!API||!/^http:\/\/127\.0\.0\.1:\d+$/.test(API)||API.endsWith(":8000"))throw new Error("S9 requires the isolated test-only API on a checked-free loopback port, never 8000.");

test("strung roof: 80% Resize previews and re-fills atomically; Delete cascades after another preview",async({page,request})=>{
 const catalog=await(await request.get(`${API}/api/catalog`)).json(); const module=catalog.modules.find((m:{revision_id:string})=>m.revision_id==="mod-rawibumi-uat-550-r1")??catalog.modules[0];
 const name=`S9 roof ${Date.now()}`; const created=await request.post(`${API}/api/projects`,{data:{name,latitude_deg:-6.2,longitude_deg:106.8,timezone:"Asia/Jakarta",workspace_mode:"blank_engineering_plane"}});expect(created.ok()).toBe(true);
 const id=(await created.json()).bundle.project.project_id; const url=`${API}/api/projects/${id}`;
 const roofResponse=await request.post(url+"/surfaces/rectangle",{data:{name:"S9 roof",width_m:20,height_m:10,base_elevation_m:6.1}});expect(roofResponse.ok()).toBe(true);const roofId=(await roofResponse.json()).bundle.scene.surfaces[0].surface_id;
 const filled=await request.post(url+"/pv-fields",{data:{name:"S9 field",support_surface_id:roofId,module_definition_revision_id:module.revision_id,tilt_deg:10,row_pitch_m:3.1,perimeter_setback_m:.5,obstacle_setback_m:.3}});expect(filled.ok()).toBe(true); const count=(await filled.json()).bundle.scene.module_instances.length;
 expect((await request.post(url+"/strings",{data:{string_length:Math.ceil(count/2),allow_shorter_remainder:true}})).ok()).toBe(true);
 const get=async()=>{const r=await request.get(url);expect(r.ok()).toBe(true);return r.json();};const before=await get();expect(before.bundle.electrical_design.strings).toHaveLength(2);
 await page.goto("/");await page.locator(".start__row",{hasText:name}).click();await expect(page.locator(".rail")).toBeVisible();await page.keyboard.press("Alt+3");await page.locator(".taskpanel .layer__name",{hasText:"S9 roof"}).click();
 const bodies:any[]=[];page.on("request",(r)=>{if(r.method()==="POST"&&r.url().endsWith(`/projects/${id}/scene/commands`))bodies.push(r.postDataJSON());});
 const inspector=page.locator(".inspectorpane");await inspector.getByRole("spinbutton",{name:"Resize %",exact:true}).fill("80");await inspector.getByRole("button").filter({hasText:/^Resize$/}).click();
 const dialog=page.getByRole("alertdialog",{name:"Roof carries PV fields"});await expect(dialog).toContainText("S9 field");await expect(dialog).toContainText(`Modules: ${count} →`);await expect(dialog).toContainText("STC power:");for(const string of before.bundle.electrical_design.strings)await expect(dialog).toContainText(string.string_id);
 expect(bodies).toHaveLength(1);expect(bodies[0]).toMatchObject({dependent_fields:"apply",dry_run:true,command:{command_type:"scale",target_entity_ids:[roofId],parameters:{factor:.8,origin:[10,5]}}});expect(bodies[0]).not.toHaveProperty("discard_dependent_strings");expect(await get()).toEqual(before);
 await dialog.getByRole("button",{name:"Cancel",exact:true}).click();await expect(dialog).toBeHidden();expect(bodies).toHaveLength(1);expect(await get()).toEqual(before);
 await inspector.getByRole("button").filter({hasText:/^Resize$/}).click();await expect(dialog).toBeVisible();await dialog.getByRole("button",{name:"Confirm roof change"}).click();await expect(dialog).toBeHidden();
 await expect.poll(async()=>(await get()).bundle.scene.module_instances.length).not.toBe(count);const after=await get();expect(after.bundle.scene.pv_fields).toHaveLength(1);expect(after.bundle.scene.pv_fields[0].pv_field_id).toBe(before.bundle.scene.pv_fields[0].pv_field_id);expect(after.bundle.electrical_design.strings).toEqual([]);
 expect(bodies).toHaveLength(3);expect(bodies[2]).toEqual({command:bodies[1].command,dependent_fields:"apply",discard_dependent_strings:true});
 expect(after.bundle.scene.revision_number).toBe(before.bundle.scene.revision_number+1);expect(after.bundle.project.project_revision.revision_number).toBe(before.bundle.project.project_revision.revision_number+1);
 const vertices=after.bundle.scene.surfaces[0].boundary_2d.vertices;expect(Math.max(...vertices.map((p:number[])=>p[0]))-Math.min(...vertices.map((p:number[])=>p[0]))).toBeCloseTo(16,9);
 await page.keyboard.press("Delete");const initial=page.getByRole("alertdialog");await expect(initial).toContainText("Deletes S9 roof from the engine. Undo is available while this edit remains in session history.");await initial.getByRole("button",{name:"Delete roof and its 1 PV fields"}).click();await expect(dialog).toBeVisible();await expect(dialog).toContainText(`Modules: ${after.bundle.scene.module_instances.length} → 0`);expect(await get()).toEqual(after);
 await dialog.getByRole("button",{name:"Confirm roof change"}).click();await expect(dialog).toBeHidden();await expect.poll(async()=>(await get()).bundle.scene.surfaces.length).toBe(0);const deleted=await get();expect(deleted.bundle.scene.pv_fields).toEqual([]);expect(deleted.bundle.scene.module_instances).toEqual([]);expect(deleted.bundle.electrical_design.strings).toEqual([]);
 expect(bodies.at(-1)).toEqual({command:bodies.at(-2).command,dependent_fields:"apply"});
});
