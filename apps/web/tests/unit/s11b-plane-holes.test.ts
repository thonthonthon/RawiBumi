import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { api } from "../../src/api";
import { centroid, enginePlaneToUi, planeZ, uiPlaneToEngine, type PlaneDef, type Vec2 } from "../../src/geometry";
import { useEntityEdits } from "../../src/canvas/useEntityEdits";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { resetStore, uiStore } from "../../src/state/store";
import type { ProjectView } from "../../src/types";
vi.mock("react", async(importOriginal) => ({...await importOriginal<typeof import("react")>(), useCallback: (fn: unknown) => fn }));
vi.mock("../../src/state/store", async(importOriginal) => ({...await importOriginal<typeof import("../../src/state/store")>(), useActions: () => uiStore.getState(), useUI: (select: (state: unknown) => unknown) => select(uiStore.getState().state) }));
const rings: Vec2[][] = [[[0,0],[12,0],[12,8],[0,8]], [[1,2],[8,3],[9,9],[-2,7]]];
const canonicalZ = (poly:Vec2[], p:PlaneDef, at:Vec2) => {
  const engine=uiPlaneToEngine(poly,p),r=engine.elevation_reference;
  const ref=r?.mode==="explicit_xy"?[r.x_m,r.y_m]:centroid(poly),a=engine.azimuth_deg*Math.PI/180;
  return engine.base_elevation_m-Math.tan(engine.slope_deg*Math.PI/180)*((at[0]-ref[0])*Math.sin(a)+(at[1]-ref[1])*Math.cos(a));
};
it.each(["down","up"] as const)("edge plane parity on all edges and both windings (%s)",(direction)=>{
 for(const ring of rings) for(const poly of [ring,[...ring].reverse()]) for(let edgeIndex=0;edgeIndex<poly.length;edgeIndex++) {
  const p:PlaneDef={mode:"edge_tilt",edgeIndex,zRef_m:7.25,tilt_deg:13.5,direction};
  for(const at of [...poly,centroid(poly)])expect(Math.abs(planeZ(poly,p,at)!-canonicalZ(poly,p,at))).toBeLessThanOrEqual(1e-9);
 }
});
it.each([0,15,90,180,275,359.9])("datum plane parity at azimuth %s",(slopeAzimuth_deg)=>{
 const p:PlaneDef={mode:"datum_tilt_azimuth",datum:[2.5,-4],z_m:9.5,tilt_deg:12,slopeAzimuth_deg};
 for(const poly of rings)for(const at of poly)expect(Math.abs(planeZ(poly,p,at)!-canonicalZ(poly,p,at))).toBeLessThanOrEqual(1e-9);
 const mapped=enginePlaneToUi(rings[0],uiPlaneToEngine(rings[0],p));
 for(const at of rings[0])expect(planeZ(rings[0],mapped,at)).toBeCloseTo(planeZ(rings[0],p,at)!,12);
});
let view:ProjectView;
beforeEach(async()=>{resetStore();setDemoLatency(0);view=await mockApi.createProject({name:"S11b",latitude_deg:-6.2,longitude_deg:106.8,timezone:"Asia/Jakarta",workspace_mode:"blank_engineering_plane"});
 view=await mockApi.sceneCommand("demo-project",{command_type:"draw_polygon",target_entity_ids:[],parameters:{name:"Roof",surface_type:"flat_roof",vertices:rings[0],base_elevation_m:6}});
 uiStore.getState().dispatch({type:"setView",view});});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();resetStore();setDemoLatency(1);});
it("A1 refuses the exact-zero centroid cross without sending a request, but accepts zero tilt",async()=>{
 const polygon:Vec2[]=[[0,0],[2,0],[2,2],[4,2],[4,5],[2,5],[2,3],[0,3]];
 const plane:PlaneDef={mode:"edge_tilt",edgeIndex:1,zRef_m:8,tilt_deg:10,direction:"down"};
 expect(()=>uiPlaneToEngine(polygon,plane)).toThrow("Choose another reference edge");
 expect(uiPlaneToEngine(polygon,{...plane,tilt_deg:0}).slope_deg).toBe(0);
 const fetch=vi.fn();vi.stubGlobal("fetch",fetch);
 await useEntityEdits().editPlane({...uiStore.getState().state.entities[0],polygon},plane);
 expect(fetch).not.toHaveBeenCalled();expect(uiStore.getState().state.toasts.at(-1)?.text).toContain("another reference edge");
});
it.each([
 ["add_hole",{vertices:[[2,2],[4,2],[4,4],[2,4]]}], ["remove_hole",{hole_index:0}],
 ["move_vertex",{ring:1,vertex_index:0,target_x_m:2.1,target_y_m:2}], ["insert_vertex",{ring:1,edge_index:0,x_m:3,y_m:2}],
 ["delete_vertex",{ring:1,vertex_index:1}], ["move_edge",{ring:1,edge_index:2,dx_m:0,dy_m:.2}]
] as const)("preserves %s and ring parameters in the canonical request",async(kind,parameters)=>{
 const fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify(view),{status:200,headers:{"Content-Type":"application/json"}}));vi.stubGlobal("fetch",fetch);
 await api.sceneCommand("p",{command_type:kind,target_entity_ids:["roof"],parameters},{dependent_fields:"apply",dry_run:true});
 const body=JSON.parse(fetch.mock.calls[0][1].body);expect(body.command.parameters).toEqual(parameters);expect(body.dependent_fields).toBe("apply");expect(body.dry_run).toBe(true);
});
it("maps saved engine planes and holes without drafts and the demo can edit and remove a ring",async()=>{
 const id=view.bundle.scene.surfaces[0].surface_id;
 view=await mockApi.sceneCommand("demo-project",{command_type:"add_hole",target_entity_ids:[id],parameters:{vertices:[[2,2],[4,2],[4,4],[2,4]]}});
 view=await mockApi.sceneCommand("demo-project",{command_type:"edit_plane",target_entity_ids:[id],parameters:{...uiPlaneToEngine(rings[0],{mode:"datum_tilt_azimuth",datum:[1,1],z_m:8,tilt_deg:8,slopeAzimuth_deg:120})}});
 uiStore.getState().dispatch({type:"setView",view});const entity=uiStore.getState().state.entities[0];
 expect(entity.holes).toHaveLength(1);expect(entity.plane.mode).toBe("datum_tilt_azimuth");expect(entity.modified).toBe(false);expect(entity.pending).toEqual([]);
 view=await mockApi.sceneCommand("demo-project",{command_type:"move_vertex",target_entity_ids:[id],parameters:{ring:1,vertex_index:0,target_x_m:2.2,target_y_m:2}});
 expect(view.bundle.scene.surfaces[0].boundary_2d?.holes[0][0]).toEqual([2.2,2]);
 view=await mockApi.sceneCommand("demo-project",{command_type:"remove_hole",target_entity_ids:[id],parameters:{hole_index:0}});
 expect(view.bundle.scene.surfaces[0].boundary_2d?.holes).toEqual([]);
});

it.each([0,1])("keeps the outer request shape unchanged and sends ring only for holes (ring=%s)",async(ring)=>{
 const fetch=vi.fn().mockImplementation(()=>Promise.resolve(new Response(JSON.stringify(view),{status:200,headers:{"Content-Type":"application/json"}})));vi.stubGlobal("fetch",fetch);
 const entity={...uiStore.getState().state.entities[0],holes:[[[2,2],[4,2],[4,4],[2,4]] as Vec2[]]};
 const edits=useEntityEdits();
 await edits.moveVertex(entity,0,[2.1,2],ring);await edits.insertVertex(entity,0,[3,2],ring);
 await edits.deleteVertex(entity,1,ring);await edits.moveEdge(entity,0,.1,ring);
 expect(fetch).toHaveBeenCalledTimes(4);
 for(const call of fetch.mock.calls){const parameters=JSON.parse(call[1].body).command.parameters;
  if(ring===0)expect(parameters).not.toHaveProperty('ring');else expect(parameters.ring).toBe(1);
 }
});
