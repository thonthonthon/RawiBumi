import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {api} from "../../src/api";
import {engine} from "../../src/client";
import {mockApi,setDemoLatency} from "../../src/demo/mockApi";
import {resetStore,uiStore,type Entity} from "../../src/state/store";
import {undo,redo,engineCommand} from "../../src/state/history";
import {ApiError,type ProjectView} from "../../src/types";
import {typingTarget} from "../../src/commands/keys";
import {isValidElement,type ReactElement} from "react";
import i18n from "../../src/i18n";
import {Inspector} from "../../src/Inspector";
import {Field} from "../../src/ui/kit";
import {useEntityEdits} from "../../src/canvas/useEntityEdits";

// Hook harness: render function components directly without a DOM dependency.
vi.mock("react",async load=>({...await load<typeof import("react")>(),useState:(v:unknown)=>[v,()=>{}],useMemo:(f:()=>unknown)=>f(),useCallback:(f:unknown)=>f}));
vi.mock("react-i18next",()=>({useTranslation:()=>({t:i18n.t.bind(i18n)}),initReactI18next:{type:"3rdParty",init(){}}}));
vi.mock("../../src/state/store",async load=>({...await load<typeof import("../../src/state/store")>(),useActions:()=>uiStore.getState(),useUI:(select:(state:unknown)=>unknown)=>select(uiStore.getState().state)}));
const tree=(value:unknown):ReactElement<any>[]=>Array.isArray(value)?value.flatMap(tree):isValidElement(value)?[value as ReactElement<any>,...tree((value as ReactElement<any>).props.children)]:[];
const nameInput=()=>{const entity=Inspector() as ReactElement<any>;const nodes=tree((entity.type as (p:unknown)=>unknown)(entity.props));
 return tree(nodes.find(n=>n.type===Field&&n.props.label==="Name")!.props.children).find(n=>n.type==="input")!;};

const draft=(id:string):Entity=>({id,kind:"surface",subtype:"flat_roof",name:id,polygon:[[0,0],[1,0],[1,1]],holes:[],plane:{mode:"flat",z_m:0},height_m:0,source:"draft",modified:false,pending:[],locked:false,hidden:false,hostsPvField:false});
const history=(limit:number,ids:string[])=>({limit,past:ids.map(entry_id=>({entry_id,label:entry_id})),future:[],reason:null});
let base:ProjectView;
beforeEach(async()=>{resetStore();setDemoLatency(0);base=structuredClone(await mockApi.project("demo-project"));});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});

it.each([1,10,100])("caps the combined history at the server limit %s",limit=>{
 base.history=history(limit,[]);uiStore.getState().dispatch({type:"setView",view:base});
 for(let i=0;i<limit+3;i++)uiStore.getState().dispatch({type:"addEntity",entity:draft(`d${i}`)});
 expect(uiStore.getState().state.past).toHaveLength(limit);
});

it("pushes owned mutation responses centrally, deduplicates wrappers, and never pushes a GET",async()=>{
 base.history=history(10,[]);const {dispatch,run}=uiStore.getState();dispatch({type:"setView",view:base});
 const changed=structuredClone(base);changed.history=history(10,["owned"]);
 vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(JSON.stringify(changed),{status:200})));
 const v=await run("Settings",()=>api.updateProject("demo-project",{name:"New"}));
 expect(uiStore.getState().state.past).toMatchObject([{kind:"engine",entryId:"owned"}]);
 dispatch({type:"engineCommitted",view:v!,label:"Again"});dispatch({type:"setView",view:v!});
 expect(uiStore.getState().state.past).toHaveLength(1);
 const read=structuredClone(changed);read.history=history(10,["owned","external"]);
 vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(JSON.stringify(read),{status:200})));
 dispatch({type:"setView",view:await api.project("demo-project")});
 expect(uiStore.getState().state.past).toHaveLength(1);
});

it("interleaves local and engine entries and sends the observed entry and revision fences",async()=>{
 base.history=history(10,["engine1"]);const {dispatch}=uiStore.getState();
 const initial=structuredClone(base);initial.history=history(10,[]);dispatch({type:"setView",view:initial});
 dispatch({type:"addEntity",entity:draft("before")});dispatch({type:"engineCommitted",view:base,label:"Engine"});
 dispatch({type:"addEntity",entity:draft("after")});
 await undo();expect(uiStore.getState().state.entities.some(e=>e.id==="after")).toBe(false);
 const undone=structuredClone(base);undone.history={...history(10,[]),future:[{entry_id:"engine1",label:"Engine"}]};
 const operation=vi.spyOn(engine,"undo").mockResolvedValue(undone);
 await undo();expect(operation).toHaveBeenCalledWith("demo-project",{expected_project_revision_id:base.bundle.project.project_revision.project_revision_id,expected_entry_id:"engine1"});
 expect(uiStore.getState().state.past.map(e=>e.kind)).toEqual(["local"]);
 await undo();await redo();vi.spyOn(engine,"redo").mockResolvedValue(base);await redo();
 expect(uiStore.getState().state.past.map(e=>e.kind)).toEqual(["local","engine"]);
});

it("clears unreachable redo on a local branch, and trims an evicted engine prefix",()=>{
 const {dispatch}=uiStore.getState();base.history=history(10,[]);dispatch({type:"setView",view:base});
 dispatch({type:"addEntity",entity:draft("old")});const v=structuredClone(base);v.history=history(10,["gone"]);
 dispatch({type:"engineCommitted",view:v,label:"Gone"});dispatch({type:"addEntity",entity:draft("new")});
 const evicted=structuredClone(v);evicted.history=history(10,[]);dispatch({type:"setView",view:evicted});
 expect(uiStore.getState().state.past.map(e=>e.kind)).toEqual(["local"]);
 dispatch({type:"undo"});expect(uiStore.getState().state.future).toHaveLength(1);
 dispatch({type:"addEntity",entity:draft("branch")});expect(uiStore.getState().state.future).toHaveLength(0);
 dispatch({type:"setView",view:null});expect(uiStore.getState().state.past).toHaveLength(0);
});

it("handles history 409 without GET, retry or changing the ordinary conflict path",async()=>{
 base.history=history(10,["e"]);const initial=structuredClone(base);initial.history=history(10,[]);
 const {dispatch}=uiStore.getState();dispatch({type:"setView",view:initial});dispatch({type:"engineCommitted",view:base,label:"Edit"});
 const read=vi.spyOn(engine,"project");const operation=vi.spyOn(engine,"undo").mockRejectedValue(new ApiError("Unavailable",409,{reason:"revision_mismatch"}));
 await undo();expect(operation).toHaveBeenCalledTimes(1);expect(read).not.toHaveBeenCalled();
 expect(uiStore.getState().state.past).toHaveLength(0);expect(uiStore.getState().state.future).toHaveLength(0);
 expect(uiStore.getState().state.toasts.at(-1)?.text).toBe("Undo history is no longer available");
});

it("ignores a busy double press and groups multiple/mixed deletion in one step",async()=>{
 const {dispatch}=uiStore.getState();dispatch({type:"setView",view:base});
 dispatch({type:"addEntity",entity:draft("a")});dispatch({type:"addEntity",entity:draft("b")});
 dispatch({type:"engineCommitted",view:base,label:"Deleting"});
 dispatch({type:"deleteEntities",ids:["a","b"],mergeEngine:true});
 expect(uiStore.getState().state.past).toHaveLength(3);
 const operation=vi.spyOn(engine,"undo").mockResolvedValue(base);dispatch({type:"busy",label:"Undoing deleting"});await undo();expect(operation).not.toHaveBeenCalled();
 dispatch({type:"busy",label:null});await undo();expect(uiStore.getState().state.entities.filter(e=>["a","b"].includes(e.id))).toHaveLength(2);
});

it("typing targets retain native undo routing",()=>{
 for(const tag of ["input","textarea","select"]){const e={tagName:tag.toUpperCase(),type:"text"} as unknown as EventTarget;expect(typingTarget(e)).toBe(true);}
 expect(typingTarget({tagName:"CANVAS"} as unknown as EventTarget)).toBe(false);
});

it("Inspector Name is uncontrolled, commits once on Enter then blur, and records nothing when unchanged",async()=>{
 await i18n.changeLanguage("en");
 const {dispatch}=uiStore.getState();base.history=history(10,[]);dispatch({type:"setView",view:base});
 dispatch({type:"addEntity",entity:draft("roof")});dispatch({type:"select",ids:["roof"]});
 const steps=()=>uiStore.getState().state.past.length;const before=steps();
 let input=nameInput();
 // No value/onChange: keystrokes stay in the browser's native text undo until commit.
 expect(input.props.value).toBeUndefined();expect(input.props.onChange).toBeUndefined();expect(input.props.defaultValue).toBe("roof");
 const blurred=vi.fn();input.props.onKeyDown({key:"z",ctrlKey:true,currentTarget:{blur:blurred}});expect(blurred).not.toHaveBeenCalled();
 input.props.onBlur({target:{value:"roof"}});expect(steps()).toBe(before);
 input.props.onKeyDown({key:"Enter",currentTarget:{blur:()=>input.props.onBlur({target:{value:"North roof"}})}});
 expect(steps()).toBe(before+1);expect(uiStore.getState().state.entities.find(e=>e.id==="roof")?.name).toBe("North roof");
 input=nameInput();expect(input.key).toBe("roof:North roof");input.props.onBlur({target:{value:"North roof"}});
 expect(steps()).toBe(before+1);
 await undo();expect(uiStore.getState().state.entities.find(e=>e.id==="roof")?.name).toBe("roof");
});

it("an engine editPlane success adds exactly one step; the cache update records none",async()=>{
 let view=await mockApi.createProject({name:"S17",latitude_deg:-6.2,longitude_deg:106.8,timezone:"Asia/Jakarta",workspace_mode:"blank_engineering_plane"});
 view=structuredClone(await mockApi.sceneCommand("demo-project",{command_type:"draw_polygon",target_entity_ids:[],parameters:{name:"Roof",surface_type:"flat_roof",vertices:[[0,0],[12,0],[12,8],[0,8]],base_elevation_m:6}}));
 view.history=history(10,["draw"]);uiStore.getState().dispatch({type:"setView",view});
 const after=structuredClone(view);after.history=history(10,["draw","plane"]);
 const fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify(after),{status:200,headers:{"Content-Type":"application/json"}}));vi.stubGlobal("fetch",fetch);
 const entity=uiStore.getState().state.entities[0];expect(entity.source).toBe("engine");
 await useEntityEdits().editPlane(entity,{mode:"datum_tilt_azimuth",datum:[1,1],z_m:8,tilt_deg:8,slopeAzimuth_deg:120});
 expect(fetch).toHaveBeenCalledTimes(1);
 expect(uiStore.getState().state.past).toEqual([{kind:"engine",label:"draw",entryId:"draw"},{kind:"engine",label:"plane",entryId:"plane"}]);
 expect(uiStore.getState().state.entities[0].plane.mode).toBe("datum_tilt_azimuth");
});

it("an undo rejected with 422 keeps past and future and shows the error",async()=>{
 base.history=history(10,["e1","e2"]);const initial=structuredClone(base);initial.history=history(10,[]);
 const {dispatch}=uiStore.getState();dispatch({type:"setView",view:initial});
 const one=structuredClone(base);one.history=history(10,["e1"]);dispatch({type:"engineCommitted",view:one,label:"One"});
 dispatch({type:"engineCommitted",view:base,label:"Two"});
 const undone=structuredClone(base);undone.history={...history(10,["e1"]),future:[{entry_id:"e2",label:"e2"}]};
 vi.spyOn(engine,"undo").mockResolvedValueOnce(undone);await undo();
 const {past,future}=uiStore.getState().state;expect(past).toHaveLength(1);expect(future).toHaveLength(1);
 const read=vi.spyOn(engine,"project");
 vi.spyOn(engine,"undo").mockRejectedValue(new ApiError("Restored design is invalid",422,"Restored design is invalid"));await undo();
 expect(uiStore.getState().state.past).toBe(past);expect(uiStore.getState().state.future).toBe(future);
 expect(read).not.toHaveBeenCalled();
 expect(uiStore.getState().state.toasts.at(-1)).toMatchObject({tone:"error",text:"Restored design is invalid"});
});
