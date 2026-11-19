import { expect,it } from "vitest";
import i18n from "../../src/i18n";
import { mockApi,setDemoLatency } from "../../src/demo/mockApi";
import { buildResultModel,checkResultRules,modelFingerprint } from "../../src/results/model";
import { renderReportHtml,type ReportInput } from "../../src/report/template";
import { EMPTY_SYSTEM } from "../../src/site/systemInfo";
// Recorded from the accepted 8ad7e14 template and its public demo fixture.
const recordedNumbers: Record<string,string[]> = {"en":["41.8 kWp","6.20000","106.82000","12","2026","-11","-16","1","2","3","4","5","6","7","8","52","9","10","11","12","1","54.0","1,292","79.2","41.8","30.0","0.4","2","3","-01","30","4","30.0","41.8 kWp","1.39","550","550","1","1","16","0","10","2","2","16","0","10","3","3","16","0","10","4","4","14","0","10","4","5","14","0","10","0","90","180","270","39","4","5","39","0005,","9","39","6","4,482","4,212","4,644","4,536","4,698","4,482","4,752","4,969","4,806","4,590","3,996","3,834","54,006","7","64,038","1,345","62,693","1,254","61,439","4,362","57,077","228","56,849","568","56,280","619","55,661","946","54,715","438","54,277","271","54,006","8","52","52","39","9","03.","12","12","03.","06.","04","54005.6 kWh","54005.6 kWh","06.","13","03.","54005.6 kWh","54005.6 kWh","03.","03.","8760","7","8,760","06.","05","52","01.","1292 kWh","1292","41.80 kWp","06.","06","5","06.","14","10","-4","2025","-01","-01","2026","-01","-01","8,760","72","25","3","2026","-11","-16","00","00","11","12","50","95","39","39","-3.0","-1.1","-3.0"],"id":["41.8 kWp","6.20000","106.82000","12","2026","-11","-16","1","2","3","4","5","6","7","8","52","9","10","11","12","1","54.0","1,292","79.2","41.8","30.0","0.4","2","3","-01","30","4","30.0","41.8 kWp","1.39","550","550","1","1","16","0","10","2","2","16","0","10","3","3","16","0","10","4","4","14","0","10","4","5","14","0","10","0","90","180","270","4","5","0005,","9","6","4,482","4,212","4,644","4,536","4,698","4,482","4,752","4,969","4,806","4,590","3,996","3,834","54,006","7","64,038","1,345","62,693","1,254","61,439","4,362","57,077","228","56,849","568","56,280","619","55,661","946","54,715","438","54,277","271","54,006","8","52","52","9","03.","12","12","03.","06.","04","54005.6 kWh","54005.6 kWh","06.","13","03.","54005.6 kWh","54005.6 kWh","03.","03.","8760","7","8,760","06.","05","52","01.","1292 kWh","1292","41.80 kWp","06.","06","5","06.","14","10","-4","2025","-01","-01","2026","-01","-01","8,760","72","25","3","2026","-11","-16","00","00","11","12","50","95","-3.0","-1.1","-3.0"]};
const numbers=(html:string)=>html.replace(/<[^>]*>/g," ").match(/-?\d[\d,.]*(?:\s?%|\s?kWh|\s?MWh|\s?kWp)?/g)??[];
it.each(["en","id"])("renders snapshot-only method and P99 content in %s, preserving every existing numeric text",async language=>{
 setDemoLatency(0);await i18n.changeLanguage(language);
 const view=await mockApi.project("demo-project"),run=view.bundle.simulation_runs[0];
 const snapshot=await mockApi.reportSnapshot("demo-project",run.simulation_run_id);
 snapshot.method.loss_disclosures=[{code:"lid_fraction",label:"LID",fraction:0,not_included:true,suggestions:[{fraction:null,applied:false,reason:"pan_lid_not_supplied"}]}];
 const model=buildResultModel(view,run,{authority:"DEMO_SYNTHETIC",hourlyAcKw:null});
 const input:ReportInput={model,rules:checkResultRules(model,{strings:view.bundle.electrical_design.strings.length}),tier:"free",branding:"",planFigure:null,sldSvg:"<svg></svg>",charts:{monthly:"<svg></svg>",waterfall:null,heatmap:null},fingerprint:modelFingerprint(model),generatedAt:"2026-11-16 00:00 UTC",identity:{address:null,addressAttribution:null,latitude:-6.2,longitude:106.82,elevationM:12,issuedOn:"2026-11-16",system:EMPTY_SYSTEM},css:"",t:i18n.t.bind(i18n)};
 
 const html=renderReportHtml({...input,verifiedSource:snapshot});
 expect(html).toContain('data-report-method-limits');expect(html).toContain('data-report-p99-reason="no_uncertainty_ledger"');
 expect(html).toContain(language==="en" ? "0 %: not included" : "0 %: tidak dimasukkan");
 const withoutNew=html.replace(/<div data-report-snapshot-additions>[\s\S]*?<\/div><!-- snapshot-additions-end -->/g,"");
 expect(numbers(withoutNew)).toEqual(recordedNumbers[language]);
});
