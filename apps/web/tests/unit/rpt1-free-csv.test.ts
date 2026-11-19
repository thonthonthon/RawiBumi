import { afterEach, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { exportAPI } from "../../src/api";
import { FreeCSVExport } from "../../src/results/ExportView";
import { setEntitlementSource } from "../../src/platform/entitlements";
import i18n from "../../src/i18n";
afterEach(() => { vi.unstubAllGlobals(); setEntitlementSource(null); });
it("downloads through the HTTP-only Free CSV route with encoded IDs and no-store", async () => {
  const bytes=new Uint8Array([80,75,3,4,0,255]);
  const fetcher=vi.fn().mockResolvedValue(new Response(bytes,{headers:{'Content-Type':'application/zip'}}));
  vi.stubGlobal('fetch',fetcher);
  const blob=await exportAPI.freeCSV('project /é','run /?');
  expect(new Uint8Array(await blob.arrayBuffer())).toEqual(bytes);
  expect(fetcher).toHaveBeenCalledWith('/api/projects/project%20%2F%C3%A9/runs/run%20%2F%3F/exports/free-csv',{cache:'no-store'});
});
it("preserves a server refusal and rejects a non-ZIP response", async () => {
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(Response.json({detail:'PR does not reconcile'},{status:422})));
  await expect(exportAPI.freeCSV('p','r')).rejects.toThrow('PR does not reconcile');
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('not zip',{headers:{'Content-Type':'text/html'}})));
  await expect(exportAPI.freeCSV('p','r')).rejects.toThrow('application/zip');
});
it("shows the Free action in en and id and gates it with the compatible capability", async () => {
  for (const [language,label] of [['en','Download Free CSV'],['id','Unduh CSV Gratis']]) {
    await i18n.changeLanguage(language);
    expect(renderToStaticMarkup(createElement(FreeCSVExport, {projectId:"p",runId:"r"}))).toContain(label);
  }
  setEntitlementSource(f=>f!=="core.export.csv-basic");
  expect(renderToStaticMarkup(createElement(FreeCSVExport, {projectId:"p",runId:"r"}))).not.toContain('data-free-csv-export');
});
