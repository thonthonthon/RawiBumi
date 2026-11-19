import { beforeEach, expect, it, vi } from "vitest";
import { isValidElement, type ReactElement } from "react";
const h=vi.hoisted(()=>({slots:[] as any[],cursor:0,state:{view:{bundle:{project:{project_id:"p"}}},busy:null} as any,
 run:vi.fn(),dispatch:vi.fn(),toast:vi.fn(),list:vi.fn(),preview:vi.fn(),commit:vi.fn(),hide:vi.fn(),unhide:vi.fn(),project:vi.fn()}));
vi.mock("react",async(load)=>({...await load<typeof import("react")>(),useState:(value:unknown)=>{const i=h.cursor++;if(!(i in h.slots))h.slots[i]=value;return[h.slots[i],(next:unknown)=>h.slots[i]=next];},useEffect:()=>{}}));
vi.mock("react-i18next",async(load)=>({...await load<typeof import("react-i18next")>(),useTranslation:()=>({t:i18n.t.bind(i18n),i18n})}));
vi.mock("../../src/state/store",()=>({useStore:()=>({state:h.state,run:h.run,dispatch:h.dispatch,toast:h.toast}),uiStore:{getState:()=>({state:h.state})}}));
vi.mock("../../src/client",()=>({engine:{componentLibrary:h.list,previewComponent:h.preview,importComponent:h.commit,hideComponent:h.hide,unhideComponent:h.unhide,project:h.project}}));
import i18n from "../../src/i18n";
import { ImportHub } from "../../src/Modals";
import { Button } from "../../src/ui/kit";
import { ModalDialog } from "../../src/ui/ModalDialog";
import { componentCatalogLabel, type ComponentLibraryPreview } from "../../src/types";
import { api } from "../../src/api";
import { mockApi } from "../../src/demo/mockApi";
import { en } from "../../src/i18n/en";
import { id } from "../../src/i18n/id";
function tree(v:unknown):ReactElement<any>[] {if(Array.isArray(v))return v.flatMap(tree);if(!isValidElement(v))return[];const n=v as ReactElement<any>;return[n,...tree(n.props.children)];}
function render(){h.cursor=0;return tree(ImportHub({onClose:()=>{}}));}
function text(v:unknown):string {if(v==null||typeof v==="boolean")return"";if(Array.isArray(v))return v.map(text).join(" ");if(isValidElement(v))return text((v as ReactElement<any>).props.children);return String(v);}
function button(label:string){return render().find(n=>n.type===Button&&text(n.props.children)===label);}
function entryPreview():ComponentLibraryPreview{return{kind:"inverters",manufacturer:"Synthetic",model:"Test inverter",revision_id:"lib-inv-test-r1",duplicate_of:"lib-inv-test-r1",parameters:{nominal_ac_power_w:100000,max_input_current_a:null,mppt_max_operating_current_a:null,efficiency_fraction:.9882,efficiency_metric:"european"},findings:[],schema_ready:true,simulation_ready:false,readiness_findings:[],reasons:[{code:"mppt_operating_current_missing",message:"Maximum operating current per MPPT is not in the file."}]};}
async function settle(){for(let i=0;i<25;i++)await Promise.resolve();}
beforeEach(()=>{vi.clearAllMocks();vi.unstubAllGlobals();void i18n.changeLanguage("en");h.slots=[];h.state={view:{bundle:{project:{project_id:"p"}}},busy:null};h.run.mockImplementation(async(_label,op)=>{try{return await op();}catch{return undefined;}});h.list.mockResolvedValue([]);h.project.mockResolvedValue(h.state.view);});
it("preview shows units, missing physical limits, European metric and layout-only duplicate notice",()=>{
 h.slots=["components",new File(["synthetic"],"test.ond"),entryPreview()];const nodes=render(),all=text(nodes);
 expect(all).toContain("Layout only");expect(all).toContain("Maximum total DC input current");expect(all).toContain("Maximum operating current per MPPT");expect(all).toContain("— (not in file)");expect(all).toContain(" A");expect(all).toContain("European efficiency");expect(all).toContain("98.82");expect(all).toContain("%");expect(all).toContain("Already in the library as lib-inv-test-r1.");expect(button("Import to library")).toBeDefined();
});
it("module temperature coefficients keep explicit units and schema-incomplete previews cannot commit",()=>{
 const p={...entryPreview(),kind:"modules" as const,schema_ready:false,parameters:{gamma_pmp_pct_per_c:-.345,mu_voc_v_per_c:-.1379,cell_count:null}};h.slots=["components",new File(["synthetic"],"test.pan"),p];const all=text(render());expect(all).toContain("%/°C");expect(all).toContain("V/°C");expect(all).toContain("-0.345");expect(all).toContain("not in file");expect(button("Import to library")).toBeUndefined();
});
it("preview is read-only; commit uses run, reloads the project/catalogue, and names the revision",async()=>{
 const file=new File(["synthetic"],"module.pan");h.slots=["components",file];h.preview.mockResolvedValue(entryPreview());button("Detect and preview")!.props.onClick();await settle();expect(h.preview).toHaveBeenCalledWith(file);expect(h.commit).not.toHaveBeenCalled();expect(h.project).not.toHaveBeenCalled();
 h.commit.mockResolvedValue({entry:entryPreview(),created:true});button("Import to library")!.props.onClick();await settle();expect(h.commit).toHaveBeenCalledWith(file);expect(h.list).toHaveBeenCalledWith(false);expect(h.project).toHaveBeenCalledWith("p");expect(h.dispatch).toHaveBeenCalledWith({type:"setView",view:h.state.view});expect(h.toast).toHaveBeenCalledWith("ok",expect.stringContaining("lib-inv-test-r1"));expect(button("Import to library")).toBeUndefined();
});
it("hide is confirmed and Cancel does not send a request; Unhide is available for hidden revisions",async()=>{
 const e={kind:"inverters",definition:{revision_id:"lib-inv-test-r1",manufacturer:"Synthetic",model:"Test"},library:{hidden:false,source_filename:"test.ond",readiness:{ready:false,findings:[]}}};h.slots=["components",null,null,[e]];
 button("Hide")!.props.onClick();expect(h.hide).not.toHaveBeenCalled();expect(render().filter(n=>n.type===ModalDialog)).toHaveLength(2);button("Cancel")!.props.onClick();expect(h.hide).not.toHaveBeenCalled();
 button("Hide")!.props.onClick();render().filter(n=>n.type===Button&&text(n.props.children)==="Hide").at(-1)!.props.onClick();await settle();expect(h.hide).toHaveBeenCalledWith(e.definition.revision_id);
 h.slots[3]=[{...e,library:{...e.library,hidden:true}}];button("Unhide")!.props.onClick();await settle();expect(h.unhide).toHaveBeenCalledWith(e.definition.revision_id);
});
it("busy controls visibly refuse new commands",()=>{h.state.busy="Other command";h.slots=["components",new File(["x"],"test.pan"),entryPreview()];expect(button("Detect and preview")!.props.disabled).toBe(true);expect(button("Import to library")!.props.disabled).toBe(true);button("Detect and preview")!.props.onClick();button("Import to library")!.props.onClick();expect(h.preview).not.toHaveBeenCalled();expect(h.commit).not.toHaveBeenCalled();});
it("reference labels stay identical; both library selects use translated library/layout-only suffixes",()=>{expect(componentCatalogLabel({source:"reference"},"Reference","library","layout only")).toBe("Reference");expect(componentCatalogLabel({source:"library",simulation_ready:true},"Model","library","layout only")).toBe("Model · library");expect(componentCatalogLabel({source:"library",simulation_ready:false},"Model","pustaka","hanya tata letak")).toBe("Model · pustaka · hanya tata letak");expect(Object.keys(en.s12a).sort()).toEqual(Object.keys(id.s12a).sort());expect(Object.keys(en.s12a.params).sort()).toEqual(Object.keys(id.s12a.params).sort());});
it("raw upload adapter preserves file bytes/name and never uses multipart",async()=>{
 const file=new File([new Uint8Array([0x50,0xb0,0x56])],"synthetic degree.ond");const fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>entryPreview()});vi.stubGlobal("fetch",fetch);await api.previewComponent(file);expect(fetch.mock.calls[0][0]).toContain("filename=synthetic%20degree.ond&dry_run=true");expect(fetch.mock.calls[0][1]).toMatchObject({method:"POST",body:file,headers:{"Content-Type":"application/octet-stream"}});
});
it("every demo library operation refuses without an invented entry",async()=>{const f=new File(["x"],"test.pan");for(const operation of [()=>mockApi.componentLibrary(),()=>mockApi.previewComponent(f),()=>mockApi.importComponent(f),()=>mockApi.hideComponent("id"),()=>mockApi.unhideComponent("id")])await expect(operation()).rejects.toThrow("Importing components needs the engine");});
