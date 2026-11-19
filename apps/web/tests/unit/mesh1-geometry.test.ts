import {expect, it, afterEach, vi} from "vitest";
import {Mesh, DoubleSide} from "three";
import {buildExactGeometry, disposeGroup} from "../../src/canvas/gl/scene3d";
import {modulePlacement, fieldSupportIds, type ExactSceneGeometry, type ProjectView} from "../../src/types";
import {mockApi, setDemoLatency} from "../../src/demo/mockApi";
import {api} from "../../src/api";
const exact: ExactSceneGeometry = {
 source_scene_hash:"hash",source_scene_revision_id:"revision",bounds_3d:{min_xyz:[0,0,0],max_xyz:[4,4,8]},
 obstacles:[{obstacle_id:"mesh",obstacle_type:"imported_mesh",visible:true,mesh:{vertices_3d:[[0,0,8],[4,0,8],[4,4,8],[0,4,8]],triangles:[[3,0,1],[1,2,3]],faces:[{vertex_indices:[0,1,2,3]}]}}],
 modules:[{module_instance_id:"vertical",pv_field_id:"explicit",status:"resolved",corners_3d:[[1,1,0],[2,1,0],[2,1,2],[1,1,2]]}]
};
afterEach(()=>{vi.unstubAllGlobals();setDemoLatency(1);});
it("renders original world vertices and indexed triangles, source edges only, and exact vertical corners",()=>{
 const group=buildExactGeometry(exact,new Set(["explicit"]));
 expect(group.children).toHaveLength(4); // mesh + its original ring + module + its ring; no opaque table filler
 const mesh=group.children[0] as Mesh;
 expect(Array.from(mesh.geometry.index!.array)).toEqual([3,0,1,1,2,3]);
 expect(Array.from(mesh.geometry.getAttribute("position").array)).toEqual(exact.obstacles[0].mesh!.vertices_3d.flat());
 expect((mesh.material as {side:number}).side).toBe(DoubleSide);
 expect((group.children[1] as Mesh).geometry.getAttribute("position").count).toBe(4);
 expect(Array.from((group.children[2] as Mesh).geometry.getAttribute("position").array)).toEqual(exact.modules[0].corners_3d.flat());
 disposeGroup(group);
});
it("skips hidden meshes and native modules and refuses unresolved new modules without a surrogate",()=>{
 const data=structuredClone(exact);data.obstacles[0].visible=false;
 const group=buildExactGeometry(data,new Set());expect(group.children).toHaveLength(0);disposeGroup(group);
 data.modules[0].status="unresolved";data.modules[0].unresolved_reason="damaged table";
 expect(()=>buildExactGeometry(data,new Set(["explicit"]))).toThrow("vertical: damaged table");
});
export async function explicitView():Promise<ProjectView> {
 setDemoLatency(0);
 const view:ProjectView=structuredClone(await mockApi.createProject({name:"Synthetic MESH1",latitude_deg:0,longitude_deg:100,timezone:"UTC",workspace_mode:"blank_engineering_plane"}));
 const revision=view.catalog.modules[0].revision_id;
 view.bundle.scene.pv_fields=[{field_kind:"explicit_layout",pv_field_id:"explicit",name:"Tables",tables:[
  {table_id:"a",module_definition_revision_id:revision,tilt_deg:10,azimuth_deg:180,module_orientation:"portrait",modules_across:1,modules_up:1},
  {table_id:"b",module_definition_revision_id:view.catalog.modules[1].revision_id,tilt_deg:90,azimuth_deg:90,module_orientation:"landscape",modules_across:1,modules_up:1,support_surface_id:"roof-b"}
 ]}];
 view.bundle.scene.module_instances=[{module_instance_id:"m-a",pv_field_id:"explicit",table_id:"a",enabled:true},{module_instance_id:"m-b",pv_field_id:"explicit",table_id:"b",enabled:true}];
 view.scene_view.local_features=[];view.table_layout=undefined;
 return view;
}
it("resolves each actual table's definition and orientation; does not select the first table for a missing id",async()=>{
 const view=await explicitView();
 expect(modulePlacement(view,"m-a")).toMatchObject({tableId:"a",tiltDeg:10,azimuthDeg:180,orientation:"portrait"});
 expect(modulePlacement(view,"m-b")).toMatchObject({tableId:"b",tiltDeg:90,azimuthDeg:90,orientation:"landscape"});
 expect(modulePlacement(view,"m-b")!.revisionId).not.toBe(modulePlacement(view,"m-a")!.revisionId);
 expect(fieldSupportIds(view.bundle.scene.pv_fields[0])).toEqual(["roof-b"]);
 view.bundle.scene.module_instances[1].table_id="missing";expect(modulePlacement(view,"m-b")).toBeUndefined();
});
it("uses the real read-only derived route and forwards cancellation; demo refuses explicitly",async()=>{
 const fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify(exact),{status:200}));vi.stubGlobal("fetch",fetch);
 const controller=new AbortController();expect(await api.sceneGeometry3d("p/1",controller.signal)).toEqual(exact);
 expect(fetch.mock.calls[0][0]).toBe("/api/projects/p%2F1/scene/geometry-3d");expect(fetch.mock.calls[0][1].signal).toBe(controller.signal);
 await expect(mockApi.sceneGeometry3d("p")).rejects.toThrow("real engine");
});
