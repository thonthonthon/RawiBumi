import {afterEach,expect,it,vi} from "vitest";
import {mockApi,setDemoLatency} from "../../src/demo/mockApi";
import {dcCapacityKwp} from "../../src/results/model";
import {quantities} from "../../src/state/derived";
import {resetStore,uiStore} from "../../src/state/store";
import {moveModules,previewModuleDelete} from "../../src/canvas/useModuleEdits";
import {missingRefillParameters,legacyRefillRequest,pvFieldChanges} from "../../src/engine/layout";
import type {ProjectView} from "../../src/types";
afterEach(()=>{resetStore();setDemoLatency(1);vi.unstubAllGlobals();});
async function view():Promise<ProjectView> {
 setDemoLatency(0);const v:ProjectView=structuredClone(await mockApi.createProject({name:"Synthetic MESH1 consumer",latitude_deg:0,longitude_deg:100,timezone:"UTC",workspace_mode:"blank_engineering_plane"}));
 v.bundle.scene.pv_fields=[{field_kind:"explicit_layout",pv_field_id:"f",name:"Two different tables",tables:[
  {table_id:"a",module_definition_revision_id:v.catalog.modules[0].revision_id,tilt_deg:10,azimuth_deg:180,module_orientation:"portrait",modules_across:1,modules_up:1},
  {table_id:"b",module_definition_revision_id:v.catalog.modules[1].revision_id,tilt_deg:90,azimuth_deg:90,module_orientation:"landscape",modules_across:1,modules_up:1}
 ]}];
 v.bundle.scene.module_instances=[{module_instance_id:"a",pv_field_id:"f",table_id:"a",enabled:true},{module_instance_id:"b",pv_field_id:"f",table_id:"b",enabled:true}];
 v.scene_view.local_features=[];v.table_layout=undefined;v.bundle.electrical_design.strings=[];return v;
}
it("counts all explicit modules and both actual nameplates even without a polygon for the vertical module",async()=>{
 const v=await view();expect(dcCapacityKwp(v)).toBeCloseTo(1.16,12);
 uiStore.getState().dispatch({type:"setView",view:v});
 expect(uiStore.getState().state.modules).toHaveLength(0);
 const state=uiStore.getState().state;const result=quantities({view:v,modules:state.modules,entities:state.entities,electrical:state.electrical});expect(result).toMatchObject({modules:2,unassigned:2});expect(result.kwp).toBeCloseTo(1.16,12);
});
it("refuses exact moves and deletes of read-only explicit modules before any request",async()=>{
 const v=await view();uiStore.getState().dispatch({type:"setView",view:v});const fetch=vi.fn();vi.stubGlobal("fetch",fetch);
 await moveModules(["a"],[1,0]);await previewModuleDelete(["b"]);expect(fetch).not.toHaveBeenCalled();
 expect(uiStore.getState().state.toasts.at(-1)?.text).toContain("read-only");
});
it("never maps an explicit table into a generated re-fill request",async()=>{
 const v=await view(),f=v.bundle.scene.pv_fields[0];
 expect(missingRefillParameters(f)).toEqual(["explicit_layout_read_only"]);
 expect(legacyRefillRequest(f,{width_m:1,height_m:2},4)).toBeNull();
 // The guard must run before inspecting a generated request's values.
 expect(pvFieldChanges({} as Parameters<typeof pvFieldChanges>[0],f,{width_m:1,height_m:2}).reasons).toEqual(["Explicit layouts are read-only."]);
});
