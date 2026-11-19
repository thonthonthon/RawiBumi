import { afterEach,expect,it,vi } from "vitest";
afterEach(()=>vi.unstubAllGlobals());
it("the demo project retains its report metadata across reloads without changing its design hash",async()=>{
 const memory=new Map<string,string>();vi.stubGlobal("window",{localStorage:{getItem:(key:string)=>memory.get(key)??null,setItem:(key:string,value:string)=>memory.set(key,value),removeItem:(key:string)=>memory.delete(key)}});
 vi.resetModules();let {mockApi,setDemoLatency}=await import("../../src/demo/mockApi");setDemoLatency(0);
 const before=await mockApi.project("demo-project");
 const address={text:"Synthetic project address",source:"user" as const,lat:0,lon:0,attribution:null,updatedAt:"2026-11-16T00:00:00Z"};
 const installation={installationType:"hybrid" as const,bessEnergyKwh:10,bessPowerKw:2};
 const revision=structuredClone(before.bundle.project.project_revision);
 await mockApi.updateSiteDetails("demo-project",{address,installation});
 expect((await mockApi.project("demo-project")).bundle.project.project_revision).toEqual(revision);
 vi.resetModules();({mockApi,setDemoLatency}=await import("../../src/demo/mockApi"));setDemoLatency(0);
 const after=await mockApi.project("demo-project");
 expect(after.bundle.project.site.address).toEqual(address);expect(after.bundle.project.site.installation).toEqual(installation);
 expect(after.design_fingerprint).toBe(before.design_fingerprint);
});
it("demo Undo and Redo keep the current site details across an intervening design edit",async()=>{
 vi.resetModules();const {mockApi,setDemoLatency}=await import("../../src/demo/mockApi");setDemoLatency(0);
 await mockApi.addSurface("demo-project",{name:"Synthetic history roof",origin_x_m:100,origin_y_m:100,width_m:10,height_m:6,base_elevation_m:6,surface_type:"flat_roof"});
 const address={text:"Late lookup",source:"lookup" as const,lat:0,lon:0,attribution:null,updatedAt:"2026-11-16T00:00:00Z"};
 await mockApi.updateSiteDetails("demo-project",{address,installation:{installationType:"hybrid",bessEnergyKwh:10,bessPowerKw:2}});
 const undone=await mockApi.undo("demo-project");
 expect(undone.bundle.project.site.address).toEqual(address);
 expect(undone.bundle.project.site.installation?.bessEnergyKwh).toBe(10);
 await mockApi.updateSiteDetails("demo-project",{address:null,installation:null});
 const redone=await mockApi.redo("demo-project");
 expect(redone.bundle.project.site.address).toBeNull();expect(redone.bundle.project.site.installation).toBeNull();
});
