import { afterEach,expect,it,vi } from "vitest";
import { safeStorage } from "../../src/shell/usePanes";
import * as address from "../../src/site/address";
import * as system from "../../src/site/systemInfo";
afterEach(()=>{vi.unstubAllGlobals();});
it("copies browser metadata once and then reads the project, preserving the per-browser lookup preference",async()=>{
 const memory=new Map<string,string>();vi.stubGlobal("window",{localStorage:{getItem:(k:string)=>memory.get(k)??null,setItem:(k:string,v:string)=>memory.set(k,v)}});
 const stored={text:"Synthetic old address",source:"user",lat:0,lon:0,attribution:null,updatedAt:"2026-11-16T00:00:00Z"};
 safeStorage.setItem("rawibumi.siteAddress.rpt2b1",JSON.stringify(stored));address.setLookupAllowed(false);
 const installation={installationType:"hybrid",bessEnergyKwh:7,bessPowerKw:2};safeStorage.setItem("rawibumi.systemInfo.rpt2b1",JSON.stringify(installation));
 const site:Record<string,unknown>={};let writes=0;
 vi.stubGlobal("fetch",vi.fn(async (url:string,init?:RequestInit)=>{
  if(init?.method==="PATCH"){expect(url).toBe("/api/projects/rpt2b1/site/details");const body=JSON.parse(String(init.body));expect(body.copy_if_missing).toBe(true);delete body.copy_if_missing;Object.assign(site,body);writes++;}
  return Response.json({bundle:{project:{site}}});
 }));
 expect(await address.loadProjectAddress("rpt2b1")).toEqual(stored);
 expect(await system.loadProjectSystem("rpt2b1")).toEqual(installation);
 expect(writes).toBe(2);site.address={...stored,text:"Project address wins"};
 expect(await address.loadProjectAddress("rpt2b1")).toEqual(site.address);
 expect(await system.loadProjectSystem("rpt2b1")).toEqual(installation);
 expect(writes).toBe(2);expect(address.lookupAllowed()).toBe(false);
});
it("fetches a demo snapshot with the recorded production values and refuses a changed design",async()=>{
 const {mockApi,setDemoLatency}=await import("../../src/demo/mockApi");setDemoLatency(0);
 const view=await mockApi.project("demo-project"),run=view.bundle.simulation_runs[0];
 const result=await mockApi.reportSnapshot("demo-project",run.simulation_run_id);
 expect(result.summary).toEqual(run.summary_result);expect(result.snapshot_sha256).toMatch(/^[0-9a-f]{64}$/);
 expect(result.annual_pxx.P99).toBeNull();expect(result.annual_pxx.P99_reason).toBe("no_uncertainty_ledger");
});
it("reads site details from the open project without redundant reload requests",async()=>{
 const {mockApi,setDemoLatency}=await import("../../src/demo/mockApi");setDemoLatency(0);
 const {uiStore}=await import("../../src/state/store");
 const view=await mockApi.project("demo-project"),previous=uiStore.getState().state.view;
 const value={text:"Already loaded project address",source:"user" as const,lat:0,lon:0,attribution:null,updatedAt:"2026-11-16T00:00:00Z"};
 view.bundle.project.site.address=value;
 view.bundle.project.site.installation={installationType:"hybrid",bessEnergyKwh:10,bessPowerKw:2};
 uiStore.getState().dispatch({type:"setView",view});
 const fetch=vi.fn();vi.stubGlobal("fetch",fetch);
 try {
  expect(await address.loadProjectAddress("demo-project")).toEqual(value);
  expect(await system.loadProjectSystem("demo-project")).toEqual(view.bundle.project.site.installation);
  expect(fetch).not.toHaveBeenCalled();
 } finally {uiStore.getState().dispatch({type:"setView",view:previous});}
});
it("a late site-details response preserves a newer design view and its undo history",async()=>{
 const {mockApi,setDemoLatency}=await import("../../src/demo/mockApi");setDemoLatency(0);
 const {uiStore}=await import("../../src/state/store");
 const older=await mockApi.project("demo-project"),previous=uiStore.getState().state.view;
 older.history={limit:10,past:[],future:[],reason:null};
 uiStore.getState().dispatch({type:"setView",view:older});
 let respond!:(value:Response)=>void;
 const fetch=vi.fn(()=>new Promise<Response>(resolve=>{respond=resolve;}));vi.stubGlobal("fetch",fetch);
 const value={text:"Delayed metadata",source:"user" as const,lat:0,lon:0,attribution:null,updatedAt:"2026-11-16T00:00:00Z"};
 const saving=address.saveProjectAddress("demo-project",value);
 await vi.waitFor(()=>expect(fetch).toHaveBeenCalledOnce());
 const newer=structuredClone(older);
 newer.bundle.project.project_revision.project_revision_id+="-newer";
 newer.history!.past=[{entry_id:"newer-design-edit",label:"Edit imagery"}];
 uiStore.getState().dispatch({type:"engineCommitted",view:newer,label:"Edit imagery"});
 older.bundle.project.site.address=value;
 respond(Response.json(older));
 try {
  await saving;
  const current=uiStore.getState().state;
  expect(current.view!.bundle.project.project_revision).toEqual(newer.bundle.project.project_revision);
  expect(current.view!.history).toEqual(newer.history);
  expect(current.past.at(-1)).toMatchObject({entryId:"newer-design-edit"});
  expect(current.view!.bundle.project.site.address).toEqual(value);
 } finally {uiStore.getState().dispatch({type:"setView",view:previous});}
});
