import { beforeEach, expect, it, vi } from "vitest";
import { cloneElement, createElement, isValidElement, type ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import i18n from "../../src/i18n";
import fixture from "./s7b-engine-fixture.json";
import type { ProjectView, ResolvedShadingAccuracy, SimulationRunRecord } from "../../src/types";
import { ShadingAccuracyPanel, RunShadingAccuracy, recordedShadingSampling } from "../../src/panels/ShadingAccuracyPanel";
const h=vi.hoisted(()=>({view:null as ProjectView|null,busy:false,slots:[] as unknown[],cursor:0,update:vi.fn(),dispatch:vi.fn()}));
vi.mock("react",async load=>({...await load<typeof import("react")>(),useState:(initial:unknown)=>{const i=h.cursor++;if(!(i in h.slots))h.slots[i]=initial;return[h.slots[i],(v:unknown)=>{h.slots[i]=v;}];},useEffect:()=>undefined}));
vi.mock("react-i18next",()=>({useTranslation:()=>({t:i18n.t.bind(i18n)}),initReactI18next:{type:"3rdParty",init(){}}}));
vi.mock("../../src/client",()=>({engine:{updateShadingAccuracy:(...args:unknown[])=>h.update(...args)}}));
vi.mock("../../src/state/store",()=>({useStore:()=>({state:{view:h.view,busy:h.busy},dispatch:h.dispatch,run:async(_s:string,fn:()=>Promise<unknown>)=>fn()})}));
const standard:ResolvedShadingAccuracy={schema_version:"0.1",defaults_id:"shading_accuracy.v1",level:"standard",source:"recommended_defaults",sky_dome_resolution:{azimuth_sectors:48,elevation_bands:12,horizon_azimuth_sectors:48,horizon_elevation_bands:1,horizon_band_elevation_deg:10},ground_dome_resolution:{azimuth_sectors:48,depression_bands:12},ground_source:"preset_mapping"};
function tree(value:unknown):ReactElement<any>[]{if(Array.isArray(value))return value.flatMap(tree);if(!isValidElement(value))return[];const n=value as ReactElement<any>;return[n,...tree(n.props.children)];}
function render(){h.cursor=0;return tree(ShadingAccuracyPanel());}
beforeEach(async()=>{h.view=structuredClone(fixture.views.before) as unknown as ProjectView;h.view.resolved_shading_accuracy=structuredClone(standard);h.busy=false;h.slots=[];h.update.mockReset().mockResolvedValue(h.view);h.dispatch.mockClear();await i18n.changeLanguage("en");});
it("saves one explicit preset, disables no-op/reset defaults and visibly refuses busy clicks",async()=>{
 let nodes=render();expect(nodes.find(n=>n.props.children==="Save shading accuracy")!.props.disabled).toBe(true);expect(nodes.find(n=>n.props.children==="Reset shading accuracy")!.props.disabled).toBe(true);
 nodes.find(n=>n.type==="select")!.props.onChange({target:{value:"high"}});nodes=render();const save=nodes.find(n=>n.props.children==="Save shading accuracy")!;expect(save.props.disabled).toBe(false);save.props.onClick();await Promise.resolve();await Promise.resolve();expect(h.update).toHaveBeenCalledTimes(1);expect(h.update.mock.calls[0][1]).toEqual({overrides:{level:"high"}});
 h.busy=true;h.update.mockClear();nodes=render();expect(nodes.find(n=>n.type==="select")!.props.disabled).toBe(true);const button=nodes.find(n=>n.props.children==="Save shading accuracy")!;expect(button.props.disabled).toBe(true);button.props.onClick();await Promise.resolve();expect(h.update).not.toHaveBeenCalled();
});
it("resets an explicit project override",async()=>{
 h.view!.resolved_shading_accuracy={...standard,source:"project_override"};const reset=render().find(n=>n.props.children==="Reset shading accuracy")!;expect(reset.props.disabled).toBe(false);reset.props.onClick();await Promise.resolve();expect(h.update.mock.calls[0][1]).toEqual({reset_to_recommended_defaults:true});
});
it("uses finest-sampling labels and explains detailed cost in both languages",async()=>{
 for(const language of ["en","id"]){await i18n.changeLanguage(language);const html=renderToStaticMarkup(cloneElement(ShadingAccuracyPanel(), { open: true }));expect(html).toContain(language==="en"?"High (slower, finest sampling)":"Tinggi (lebih lambat, sampling paling rapat)");expect(html).not.toMatch(/maximum accuracy|akurasi maksimum/);}
});
it("old runs display recorded custom sampling and never inherit current defaults",()=>{
 const legacy={model_manifest:{near_shading_runtime:{sky_solver_manifest:{resolution:{azimuth_sectors:12,elevation_bands:3,horizon_azimuth_sectors:12,horizon_elevation_bands:1,horizon_band_elevation_deg:10}},ground_solver_manifest:{resolution:{azimuth_sectors:12,depression_bands:3}}}}} as unknown as SimulationRunRecord;
 const html=renderToStaticMarkup(createElement(RunShadingAccuracy,{run:legacy}));expect(html).toContain("Legacy/custom");expect(html).toContain("12 × 3");expect(html).not.toContain("48 × 12");
 const missing=renderToStaticMarkup(createElement(RunShadingAccuracy,{run:{} as SimulationRunRecord}));expect(missing).toContain("not recorded");expect(recordedShadingSampling({} as SimulationRunRecord)).toBeUndefined();
});
it("new runs show their snapshot even after the project's choice changes",()=>{
 const run={resolved_shading_accuracy:standard} as SimulationRunRecord;h.view!.resolved_shading_accuracy={...standard,level:"high"};const html=renderToStaticMarkup(createElement(RunShadingAccuracy,{run}));expect(html).toContain("Standard (recommended)");expect(html).toContain("48 × 12");expect(html).not.toContain("High (slower");
});
it("demo persists settings without changing illustrative energy and keeps old snapshots",async()=>{
 const {mockApi,setDemoLatency}=await import("../../src/demo/mockApi");setDemoLatency(0);
 try {const before=await mockApi.project("demo-project");const old=structuredClone(before.bundle.simulation_runs);await mockApi.updateShadingAccuracy("demo-project",{overrides:{level:"high"}});const high=await mockApi.simulate("demo-project");expect(high.resolved_shading_accuracy!.level).toBe("high");const saved=await mockApi.project("demo-project");expect(saved.bundle.simulation_runs.slice(0,old.length)).toEqual(old);await mockApi.updateShadingAccuracy("demo-project",{reset_to_recommended_defaults:true});expect((await mockApi.project("demo-project")).resolved_shading_accuracy!.level).toBe("standard");} finally {setDemoLatency(240);}
});
