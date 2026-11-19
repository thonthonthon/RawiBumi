import {beforeEach, expect, it, vi} from "vitest";
const harness=vi.hoisted(()=>({state: {} as any,values:[] as any[],cursor:0,effects:[] as Array<()=>void|(()=>void)>,fetch:vi.fn(),t:(key:string)=>key}));
vi.mock("react",async original=>({...await original<typeof import("react")>(),
 useMemo:(fn:()=>unknown)=>fn(),useCallback:(fn:unknown)=>fn,useRef:()=>({current:null}),
 useState:(initial:unknown)=>{const i=harness.cursor++;if(!(i in harness.values))harness.values[i]=initial;return[harness.values[i],(value:unknown)=>{harness.values[i]=value;}];},
 useEffect:(fn:()=>void|(()=>void))=>{harness.effects.push(fn);}
}));
vi.mock("react-i18next",()=>({useTranslation:()=>({t:harness.t})}));
vi.mock("../../src/client",()=>({engine:{sceneGeometry3d:harness.fetch}}));
vi.mock("../../src/state/store",()=>({useUI:(select:(s:any)=>unknown)=>select(harness.state)}));
vi.mock("../../src/canvas/useEntityEdits",()=>({useEntityEdits:()=>({commitMove:vi.fn(),raise:vi.fn()})}));
vi.mock("../../src/canvas/plan/usePlanModules",()=>({usePlanModules:()=>({modules:[]})}));
import {View3D} from "../../src/canvas/View3D";
function render(){harness.cursor=0;harness.effects=[];View3D();return harness.effects[0]();}
const flush=async()=>{await Promise.resolve();await Promise.resolve();};
beforeEach(()=>{harness.values=[];harness.fetch.mockReset();harness.state={step:"scene",selection:[],entities:[],view:{identity:{scene_hash:"h1"},bundle:{project:{project_id:"p1"},scene:{revision_id:"r1",obstacles:[],pv_fields:[]}}}};});
it("legacy-only scenes never request a new geometry feed",()=>{render();expect(harness.fetch).not.toHaveBeenCalled();});
it("ignores an obsolete project response and aborts its request",async()=>{
 let resolve!:(data:unknown)=>void;harness.fetch.mockImplementationOnce(()=>new Promise(r=>{resolve=r;})).mockResolvedValueOnce({source_scene_hash:"h2",source_scene_revision_id:"r2",modules:[],obstacles:[],bounds_3d:null});
 harness.state.view.bundle.scene.obstacles=[{obstacle_type:"imported_mesh"}];const cleanup=render();
 const signal=harness.fetch.mock.calls[0][1] as AbortSignal;expect(signal.aborted).toBe(false);
 cleanup?.();expect(signal.aborted).toBe(true);
 harness.state.view={identity:{scene_hash:"h2"},bundle:{project:{project_id:"p2"},scene:{revision_id:"r2",obstacles:[{obstacle_type:"imported_mesh"}],pv_fields:[]}}};
 render();await flush();expect(harness.values[0]).toMatchObject({source_scene_hash:"h2"});
 resolve({source_scene_hash:"h1",source_scene_revision_id:"r1"});await flush();expect(harness.values[0]).toMatchObject({source_scene_hash:"h2"});
});
it("refuses mismatched revision/hash and reports load errors without inventing geometry",async()=>{
 harness.state.view.bundle.scene.obstacles=[{obstacle_type:"imported_mesh"}];harness.fetch.mockResolvedValueOnce({source_scene_hash:"wrong",source_scene_revision_id:"r1"});render();await flush();
 expect(harness.values[0]).toBeNull();expect(harness.values[1]).toBe("mesh1.changed");
 harness.fetch.mockRejectedValueOnce(new Error("geometry refused"));render();await flush();expect(harness.values[0]).toBeNull();expect(harness.values[1]).toBe("geometry refused");
});
