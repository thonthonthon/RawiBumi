import { expect,it } from "vitest";
import { mockApi,setDemoLatency } from "../../src/demo/mockApi";
import { buildReportSnapshot } from "../../src/report/build";
import i18n from "../../src/i18n";
it("refuses unverified report input and ignores editable scientific values when a verified snapshot is supplied",async()=>{
 setDemoLatency(0);await i18n.changeLanguage("en");const view=await mockApi.project("demo-project"),run=view.bundle.simulation_runs[0];
 const source=await mockApi.reportSnapshot("demo-project",run.simulation_run_id);
 const input={view,entities:[],modules:[],runId:run.simulation_run_id,authority:"DEMO_SYNTHETIC" as const,hourlyAcKw:null,tier:"free" as const,branding:"",address:null,language:"en",t:i18n.t.bind(i18n),now:new Date("2026-11-16T00:00:00Z")};
 expect(()=>buildReportSnapshot(input)).toThrow(/verified.*snapshot/i);
 const accepted=buildReportSnapshot({...input,verifiedSource:source});
 const forged=structuredClone(view);forged.bundle.project.name="FORGED EDITABLE DATA";forged.bundle.simulation_runs[0].summary_result!.total_energy_wh+=999999;
 const after=buildReportSnapshot({...input,view:forged,verifiedSource:source});
 expect(after.modelFingerprint).toBe(accepted.modelFingerprint);expect(after.inputFingerprint).toBe(accepted.inputFingerprint);expect(after.html).not.toContain("FORGED EDITABLE DATA");
 expect(after.html).toContain("data-report-method-limits");
});
