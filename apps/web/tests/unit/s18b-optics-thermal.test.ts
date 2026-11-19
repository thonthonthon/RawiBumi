import { beforeEach, expect, it, vi } from "vitest";
import { createElement, isValidElement, type ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import i18n from "../../src/i18n";
import fixture from "./s7b-engine-fixture.json";
import type { ProjectView, ResolvedOpticsThermalSettings, SimulationRunRecord } from "../../src/types";
import { OpticsThermalPanel, RunOpticsThermalSettings, opticsDraft, opticsErrors, opticsPatch } from "../../src/panels/OpticsThermalPanel";
import { RunLossSettings, lossDraft } from "../../src/panels/LossesPanel";
import { formatNumber, formatPercent } from "../../src/formatNumbers";

const h=vi.hoisted(()=>({view:null as ProjectView|null,busy:false,slots:[] as unknown[],cursor:0,update:vi.fn(),dispatch:vi.fn()}));
vi.mock("react",async load=>({...await load<typeof import("react")>(),useState:(initial:unknown)=>{const i=h.cursor++;if(!(i in h.slots))h.slots[i]=typeof initial==="function"?(initial as ()=>unknown)():initial;return[h.slots[i],(v:unknown)=>{h.slots[i]=v;}];},useEffect:()=>undefined}));
vi.mock("react-i18next",()=>({useTranslation:()=>({t:i18n.t.bind(i18n)}),initReactI18next:{type:"3rdParty",init(){}}}));
vi.mock("../../src/client",()=>({engine:{updateOpticsThermal:(...a:unknown[])=>h.update(...a)}}));
vi.mock("../../src/state/store",()=>({useStore:()=>({state:{view:h.view,busy:h.busy},dispatch:h.dispatch,run:async(_s:string,fn:()=>Promise<unknown>)=>fn()})}));
const settings:ResolvedOpticsThermalSettings={schema_version:"0.1",defaults_id:"recommended_optics_thermal.v1",overrides:{},status:"recommended_defaults",settings_sha256:"recorded-optics-hash",sources:{},fallback_parameters:{n:1.526,K:4,L:.002,n_ar:null},values:{transposition:"perez_hourly",iam:{selection:"module_auto",fallback:"physical_glass"},thermal:{model:"steady_state",mounting_preset:"semi_integrated",u_c_w_m2k:20,u_v_w_m2k_per_ms:0,irradiance_basis:"effective"},albedo:{monthly_values:Array(12).fill(.2)}}};
function tree(value:unknown):ReactElement<any>[] {if(Array.isArray(value))return value.flatMap(tree);if(!isValidElement(value))return[];const n=value as ReactElement<any>;return[n,...tree(n.props.children)];}
function render(){h.cursor=0;return tree(OpticsThermalPanel({defaults:settings}));}
beforeEach(async()=>{h.slots=[];h.cursor=0;h.busy=false;h.update.mockReset().mockResolvedValue(fixture.views.before);h.dispatch.mockReset();h.view=structuredClone(fixture.views.before) as unknown as ProjectView;h.view.resolved_optics_thermal_settings=structuredClone(settings);await i18n.changeLanguage("en");});

it("uses dimensionless monthly albedo, custom U-values and a selectable legacy basis with inline validation",()=>{
 const initial=opticsDraft(settings);
 expect(opticsErrors(initial)).toEqual([]);
 expect(opticsErrors({...initial,month1:"1.1",uc:"0",uv:"-1"})).toEqual(["uc","uv","month1"]);
 const patch=opticsPatch(initial,{...initial,preset:"custom",uc:"27",basis:"incident_pre_iam"});
 expect(patch).toEqual({overrides:{thermal:{mounting_preset:"custom",u_c_w_m2k:27,u_v_w_m2k_per_ms:0,irradiance_basis:"incident_pre_iam"}}});
 const html=renderToStaticMarkup(createElement(OpticsThermalPanel,{defaults:settings}));
 expect(html).toContain("Fresnel, normal glass (no anti-reflective coating), used when the module has no IAM table");
 expect(html).toContain("Semi-integrated (air duct below), recommended default");
 expect(html).toContain('value="incident_pre_iam"');
});
it("untouched defaults disable save/reset, edits save once and all controls are visibly disabled while busy",async()=>{
 let nodes=render();
 for(const n of nodes.filter(n=>["Save optics and thermal","Reset optics and thermal"].includes(n.props.children)))expect(n.props.disabled).toBe(true);
 const input=nodes.find(n=>n.type==="input"&&n.props.value==="20")!;
 input.props.onChange({target:{value:"27"}});nodes=render();const save=nodes.find(n=>n.props.children==="Save optics and thermal")!;
 expect(save.props.disabled).toBe(false);await save.props.onClick();await Promise.resolve();
 expect(h.update).toHaveBeenCalledTimes(1);
 expect(h.update.mock.calls[0][1]).toEqual({overrides:{thermal:{mounting_preset:"custom",u_c_w_m2k:27,u_v_w_m2k_per_ms:0}}});
 h.busy=true;nodes=render();for(const n of nodes.filter(n=>["input","select"].includes(String(n.type))))expect(n.props.disabled).toBe(true);
});
it("selected-run optics are immutable and missing legacy snapshots never borrow the project choices",()=>{
 const recorded={...structuredClone(settings),status:"edited" as const,values:{...settings.values,transposition:"isotropic" as const},modules:{m:{module_revision_id:"pinned-r1",iam_source:"module_table" as const,alpha_absorption:.9,iam_profile_sha256:"table-hash"}}};
 const run={resolved_optics_thermal_settings:recorded} as SimulationRunRecord;
 const html=renderToStaticMarkup(createElement(RunOpticsThermalSettings,{run}));
 expect(html).toContain("Isotropic");expect(html).toContain("recorded-optics-hash");expect(html).toContain("Pinned module IAM table");
 const legacy=renderToStaticMarkup(createElement(RunOpticsThermalSettings,{run:{} as SimulationRunRecord}));expect(legacy).toContain("Legacy optics/thermal settings");expect(legacy).not.toContain("recorded-optics-hash");
});
it("polish formatting trims percentage artefacts while retaining zero and a sensible resistance precision",async()=>{
 expect(formatPercent(.07)).toBe("7");expect(formatNumber(.123456789,7)).toBe("0.1234568");
 const {mockApi,setDemoLatency}=await import("../../src/demo/mockApi");setDemoLatency(0);
 try {
 const defaults=await mockApi.simulationDefaults();const loss=defaults.loss_settings!;loss.values.soiling.monthly_fractions[0]=.07;
 expect(lossDraft(loss).month1).toBe("7");
 const html=renderToStaticMarkup(createElement(RunLossSettings,{run:{resolved_loss_settings:loss} as SimulationRunRecord}));
 expect(html).toContain("Enable transformer");expect(html).toContain("Not specified");expect(html).not.toContain("losses.transformer_enabled");
 } finally{setDemoLatency(240);}
});
it("demo round-trips and resets the separate optics object without claiming engine physics",async()=>{
 const {mockApi,setDemoLatency}=await import("../../src/demo/mockApi");setDemoLatency(0);
 try {
 const before=await mockApi.simulationDefaults();expect(before.demo).toBe(true);
 const edited=await mockApi.updateOpticsThermal("demo",{overrides:{transposition:"isotropic",thermal:{u_c_w_m2k:27}}});
 expect(edited.resolved_optics_thermal_settings?.values.thermal.u_c_w_m2k).toBe(27);
 expect(edited.resolved_optics_thermal_settings?.status).toBe("edited");
 const restored=await mockApi.updateOpticsThermal("demo",{reset_to_recommended_defaults:true});expect(restored.resolved_optics_thermal_settings?.values).toEqual(before.optics_thermal_settings!.values);
 } finally{setDemoLatency(240);}
});
it("new optics vocabulary is unbranded in both languages",async()=>{for(const language of ["en","id"]){await i18n.changeLanguage(language);expect(JSON.stringify(i18n.getResourceBundle(language,"translation").optics)).not.toMatch(/pvsyst/i);}});

it("thermal edits send only their changed fields, preserving recommended sources on a basis-only edit",async()=>{
 const initial=opticsDraft(settings);
 const basis=opticsPatch(initial,{...initial,basis:"incident_pre_iam"});
 expect(basis).toEqual({overrides:{thermal:{irradiance_basis:"incident_pre_iam"}}});
 expect(opticsPatch(initial,{...initial,preset:"open_rack",uc:"29"})).toEqual({overrides:{thermal:{mounting_preset:"open_rack"}}});
 expect(opticsPatch(initial,{...initial,preset:"custom",uv:"1.2"})).toEqual({overrides:{thermal:{mounting_preset:"custom",u_c_w_m2k:20,u_v_w_m2k_per_ms:1.2}}});
 // The UI's exact payload is checked above; real resolver source classification
 // for this same payload is covered by the S18b Python regression.
});
