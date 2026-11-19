import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { isValidElement, type ReactElement } from "react";
const h=vi.hoisted(()=>({state:{} as any,forms:{} as Record<string,any>,slots:[] as any[],deps:[] as any[],effects:[] as Array<()=>unknown>,cursor:0,t:((key:string)=>key) as any,
  dispatch:vi.fn(),run:vi.fn(),toast:vi.fn(),preview:vi.fn(),update:vi.fn(),commit:vi.fn(),previewFill:vi.fn()}));
vi.mock("react",async(load)=>({...await load<typeof import("react")>(),
 useMemo:(f:()=>unknown)=>f(),useState:(value:unknown)=>{const i=h.cursor++;if(!(i in h.slots))h.slots[i]=value;return[h.slots[i],(next:unknown)=>h.slots[i]=next];},
 useRef:(value:unknown)=>{const i=h.cursor++;if(!(i in h.slots))h.slots[i]={current:value};return h.slots[i];},
 useEffect:(effect:()=>unknown,deps:unknown[])=>{const i=h.cursor++;if(!h.deps[i]||deps.some((d,k)=>!Object.is(d,h.deps[i][k]))){h.deps[i]=deps;h.effects.push(effect);}}
}));
vi.mock("react-i18next",async(load)=>({...await load<typeof import("react-i18next")>(),useTranslation:()=>({t:h.t})}));
vi.mock("../../src/state/store",()=>({useUI:(selector:(s:any)=>unknown)=>selector(h.state),useActions:()=>({dispatch:h.dispatch,run:h.run,toast:h.toast}),
 useForm:(key:string,initial:unknown)=>{if(!(key in h.forms))h.forms[key]=initial;return[h.forms[key],(v:unknown)=>h.forms[key]=v];}}));
vi.mock("../../src/client",()=>({DEMO:false,engine:{previewFill:h.previewFill,previewPvFieldUpdate:h.preview,updatePvField:h.update}}));
vi.mock("../../src/state/history",()=>({engineCommand:h.commit}));
vi.mock("../../src/canvas/useTableEdits",()=>({tablesOfModules:()=>[],useTableEdits:()=>({})}));
import { LayoutPanel, uniqueFieldName } from "../../src/panels/LayoutPanel";
import { Field, Select, NumberInput, Button } from "../../src/ui/kit";
import { ModalDialog } from "../../src/ui/ModalDialog";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { pvFieldChanges, legacyRefillRequest } from "../../src/engine/layout";
import i18n from "../../src/i18n";
import { en } from "../../src/i18n/en";
import { id } from "../../src/i18n/id";
import { NotWiredError } from "../../src/pending";
function tree(v:unknown):ReactElement<any>[]{if(Array.isArray(v))return v.flatMap(tree);if(!isValidElement(v))return[];const n=v as ReactElement<any>;return[n,...tree(n.props.children)];}
function render(){h.cursor=0;const nodes=tree(LayoutPanel());const effects=h.effects.splice(0);for(const effect of effects)effect();return nodes;}
function control(label:string){return tree(render().find(n=>n.type===Field&&n.props.label===label)!.props.children).find(n=>n.type===Select||n.type===NumberInput)!;}
function button(text:string){return render().find(n=>n.type===Button&&n.props.children===text)!;}
async function settle(){for(let i=0;i<10;i++)await Promise.resolve();}
beforeEach(async()=>{
 vi.useRealTimers();vi.clearAllMocks();h.slots=[];h.deps=[];h.effects=[];h.forms={};setDemoLatency(0);void i18n.changeLanguage("en");h.t=i18n.t.bind(i18n);
 let view=await mockApi.project("demo-project");view=await mockApi.addSurface("demo-project",{name:"Roof B",origin_x_m:60,origin_y_m:0,width_m:12,height_m:10,base_elevation_m:6,surface_type:"flat_roof"});
 vi.useFakeTimers();view=structuredClone(view);h.state={view,busy:null,selection:[],preview:null,modules:[],entities:view.scene_view.local_features.filter(f=>f.category==="surface").map(f=>({id:f.id,name:f.name,kind:"surface",source:"engine",polygon:f.polygon}))};
 h.run.mockImplementation(async(_label,op)=>op());h.commit.mockImplementation(async(_label,op)=>{const result=await op();if(result)h.state.view=result;return result;});
 h.previewFill.mockRejectedValue(new NotWiredError("fillPreview"));
 const field=view.bundle.scene.pv_fields[0];h.preview.mockResolvedValue({dry_run:true,pv_field_id:field.pv_field_id,module_count_before:76,module_count_after:70,stc_power_w_before:41800,stc_power_w_after:38500,string_ids:["S1"],requires_discard_dependent_strings:true,requires_discard_manual_layout:false,conflicts:[]});
 const after=structuredClone(view);after.bundle.scene.pv_fields[0].tilt_deg=15;h.update.mockResolvedValue(after);
});
afterEach(()=>{vi.clearAllTimers();vi.useRealTimers();setDemoLatency(1);});

it("canvas selection loads a stored field; its default name follows the roof and its parameters are retained",()=>{
 h.state.selection=["srf-roof-a"];render();expect(h.forms['layout.fill']).toMatchObject({surface:"srf-roof-a",fieldId:"fld-a",name:"Roof A array"});
 h.forms['layout.fill'].tilt=23;h.forms['layout.fill'].edgeSetbacks=[1,2,3,4];h.forms['layout.fill'].sameSetback=false;h.forms['layout.fill'].gap=.04;const roof=h.state.view.bundle.scene.surfaces.at(-1);h.state.selection=[roof.surface_id];render();
 expect(h.forms['layout.fill']).toMatchObject({surface:roof.surface_id,fieldId:null,name:"Roof B array",tilt:23,edgeSetbacks:[1,2,3,4],sameSetback:false,gap:.04});
});
it("A3 preserves a stored custom field name when switching to an empty roof",()=>{
 h.state.view.bundle.scene.pv_fields[0].name="Custom saved array";h.state.selection=["srf-roof-a"];render();
 const roof=h.state.view.bundle.scene.surfaces.at(-1);control("Support surface").props.onChange(roof.surface_id);
 expect(h.forms['layout.fill']).toMatchObject({surface:roof.surface_id,fieldId:null,name:"Custom saved array"});
});
it("A3 preserves a typed name when switching to a roof without a field",()=>{
 render();const name=render().find(n=>n.type===Field&&n.props.label==="Field name")!;
 tree(name.props.children).find(n=>n.type==="input")!.props.onChange({target:{value:"Golden"}});
 const roof=h.state.view.bundle.scene.surfaces.at(-1);control("Support surface").props.onChange(roof.surface_id);
 expect(h.forms['layout.fill']).toMatchObject({surface:roof.surface_id,fieldId:null,name:"Golden"});
});
it.each(["default","empty"])("A3 replaces an untouched %s name with the new roof's default",(kind)=>{
 render();expect(h.forms['layout.fill'].name).toBe("Roof A array 2");
 if(kind==="empty")h.forms['layout.fill'].name="";
 const roof=h.state.view.bundle.scene.surfaces.at(-1);control("Support surface").props.onChange(roof.surface_id);
 expect(h.forms['layout.fill']).toMatchObject({surface:roof.surface_id,fieldId:null,name:"Roof B array"});
});
it("module, obstacle, multiple and empty selections leave the target alone; a draft cannot retarget",()=>{
 h.state.selection=["srf-roof-a"];render();const form=structuredClone(h.forms['layout.fill']);
 h.state.entities.push({id:"draft",kind:"surface",source:"draft",polygon:[]});
 for(const selection of [["m001"],["obs-ahu-1"],["srf-roof-a","obs-ahu-1"],[],["draft"]]){h.state.selection=selection;render();expect(h.forms['layout.fill']).toEqual(form);}
});
it("both controls stay enabled, and the roof dropdown switches to that roof instead of moving the field",()=>{
 h.state.selection=["srf-roof-a"];render();expect(control("Support surface").props.disabled).not.toBe(true);expect(control("Module").props.disabled).not.toBe(true);
 const roof=h.state.view.bundle.scene.surfaces.at(-1);control("Support surface").props.onChange(roof.surface_id);
 expect(h.forms['layout.fill']).toMatchObject({surface:roof.surface_id,fieldId:null});
 control("Support surface").props.onChange("srf-roof-a");expect(h.forms['layout.fill'].fieldId).toBe("fld-a");
 expect(h.update).not.toHaveBeenCalled();
});
it("preview Cancel leaves refill without a commit; success clears it and sends only the preview's required flags",async()=>{
 h.state.selection=["srf-roof-a"];render();control("Tilt").props.onChange(15);button("Apply re-fill").props.onClick();await settle();
 render().find(n=>n.type===ModalDialog)!.props.onClose();expect(h.forms['layout.fill'].fieldId).toBeNull();expect(h.update).not.toHaveBeenCalled();
 render();await vi.advanceTimersByTimeAsync(200);expect(h.previewFill).not.toHaveBeenCalled();expect(h.preview).toHaveBeenCalledOnce();
 control("Support surface").props.onChange("srf-roof-a");control("Tilt").props.onChange(15);button("Apply re-fill").props.onClick();await settle();
 button("Confirm re-fill").props.onClick();await settle();
 expect(h.update.mock.calls[0][1]).toBe("fld-a");expect(h.update.mock.calls[0][3]).toEqual({discard_dependent_strings:true});
 expect(h.forms['layout.fill']).toMatchObject({surface:"srf-roof-a",fieldId:null,name:"Roof A array 2"});
 expect(control("Support surface").props.disabled).not.toBe(true);expect(control("Module").props.disabled).not.toBe(true);
});
it("multiple fields choose the first ID and list their names; defaults take the first unused suffix",()=>{
 const fields=h.state.view.bundle.scene.pv_fields;fields.push({...fields[0],pv_field_id:"000-first",name:"First array"});h.state.selection=["srf-roof-a"];render();
 expect(h.forms['layout.fill'].fieldId).toBe("000-first");expect(JSON.stringify(render())).toContain("First array");
 expect(uniqueFieldName("Roof B array",[{name:"Roof B array"},{name:"Roof B array 2"},{name:"Roof B array 4"}])).toBe("Roof B array 3");
});
it("module mapping emits the revision only when changed and still refuses a surface change",()=>{
 const field=h.state.view.bundle.scene.pv_fields[0],mod=h.state.view.catalog.modules[0],request=legacyRefillRequest(field,mod,4)!;
 expect(pvFieldChanges(request,field,mod).changes).not.toHaveProperty("module_definition_revision_id");
 expect(pvFieldChanges({...request,module_definition_revision_id:"other-module"},field,mod).changes).toEqual({module_definition_revision_id:"other-module"});
 expect(pvFieldChanges({...request,support_surface_id:"other-roof"},field,mod).reasons).toEqual(["A re-fill keeps the support surface."]);
});
it("demo module replacement refuses honestly without changing the project; new strings exist in en and id",async()=>{
 vi.useRealTimers();const before=structuredClone(await mockApi.project("demo-project"));
 await expect(mockApi.previewPvFieldUpdate("demo-project","fld-a",{module_definition_revision_id:"mod-demo-golden-400"})).rejects.toThrow("Changing the module needs the engine");
 expect(await mockApi.project("demo-project")).toEqual(before);
 const unchanged=await mockApi.previewPvFieldUpdate("demo-project","fld-a",{name:"Renamed",module_definition_revision_id:"mod-demo-550"});
 const omitted=await mockApi.previewPvFieldUpdate("demo-project","fld-a",{name:"Renamed"});
 expect(unchanged).toEqual(omitted);expect(unchanged.string_ids).toEqual([]);
 for(const key of Object.keys(en.rf1))expect(typeof id.rf1[key as keyof typeof id.rf1]).toBe("string");
});
