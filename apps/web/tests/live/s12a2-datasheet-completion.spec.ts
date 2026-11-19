import { expect,test as base,type APIRequestContext,type Page } from "@playwright/test";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { readFileSync,mkdirSync,mkdtempSync,rmSync } from "node:fs";
import path from "node:path";
let API=process.env.RAWIBUMI_API;
if(!API||!/^http:\/\/127\.0\.0\.1:\d+$/.test(API)||API.endsWith(':8000'))throw new Error('S12a2 requires the isolated API, never a user store.');
const ROOT=path.resolve(process.cwd(),'../..');

// Global visibility is intentionally shared by projects. This file gets a separate
// disposable service so its imports/hides cannot race other files' view assertions.
const test=base.extend<{}, {componentLibraryApi:string}>({
 componentLibraryApi:[async({},use)=>{
  mkdirSync(path.join(ROOT,'tmp'),{recursive:true});
  const directory=mkdtempSync(path.join(ROOT,'tmp','s12a2-library-live-'));
  const script=`import runpy
from pathlib import Path
runpy.run_path("apps/web/scripts/serve-live-test-api.py",run_name="s12a2_test_catalog")
from apps.api.server import create_app
import uvicorn
uvicorn.run(create_app(store_root=Path(${JSON.stringify(directory)})/"projects",library_root=Path(${JSON.stringify(directory)})/"component-library"),host="127.0.0.1",port=0,timeout_keep_alive=75)
`;
  const child=spawn(path.join(ROOT,'.venv/bin/python'),['-c',script],{cwd:ROOT,stdio:['ignore','pipe','pipe']});
  let logs='';
  try{
   API=await new Promise<string>((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error(`S12a2 isolated API startup timed out: ${logs}`)),20000);
    const data=(chunk:Buffer)=>{logs+=chunk.toString();const address=logs.match(/Uvicorn running on (http:\/\/127\.0\.0\.1:\d+)/);if(address){clearTimeout(timer);resolve(address[1]);}};
    child.stdout.on('data',data);child.stderr.on('data',data);
    child.once('error',error=>{clearTimeout(timer);reject(error);});
    child.once('exit',code=>{clearTimeout(timer);reject(new Error(`S12a2 isolated API exited ${code}: ${logs}`));});
   });
   await use(API);
  }finally{
   if(child.exitCode===null&&child.signalCode===null){const closed=once(child,'exit');child.kill('SIGTERM');await closed;}
   rmSync(directory,{recursive:true,force:true});
  }
 },{scope:'worker',auto:true}],
 page:async({page,componentLibraryApi},use)=>{
  await page.route('**/api/**',async route=>{
   const source=new URL(route.request().url());
   const response=await route.fetch({url:componentLibraryApi+source.pathname+source.search});
   await route.fulfill({response});
  });
  await use(page);
 }
});

test('cited datasheet completion produces a ready revision selectable by a project', async ({page, request}) => {
 const name = `S12a2 ${Date.now()}`;
 const created = await request.post(`${API}/api/projects`, {data: {name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: 'Asia/Jakarta'}});
 expect(created.status()).toBe(201);
 const pid = (await created.json()).bundle.project.project_id;
 await page.goto('/'); await page.locator('.start__row', {hasText: name}).click(); await expect(page.locator('.rail')).toBeVisible();
 await page.keyboard.press('Alt+2'); await page.getByRole('button', {name: 'Import PAN / template…'}).click();
 const hub = page.getByRole('dialog', {name: 'Import', exact: true});
 await hub.getByLabel('Choose a file').setInputFiles(path.join(ROOT, 'tests/fixtures/panond/manufacturer/Huawei_Sun2000_100KTL_M1.OND'));
 const previewResponse = page.waitForResponse(r => r.url().includes('/component-library/imports?') && r.url().includes('dry_run=true'));
 await hub.getByRole('button', {name: 'Detect and preview'}).click(); const initial = await previewResponse; expect(initial.status()).toBe(200);
 const rid = (await hub.getByRole('region', {name: 'Component preview'}).locator('code').first().innerText()).trim();
 await expect(hub.getByRole('region', {name: 'Component preview'})).toContainText('maximum operating current per MPPT is not in the file');
 const importResponse = page.waitForResponse(r => r.url().includes('/component-library/imports?') && r.url().includes('dry_run=false'));
 await hub.getByRole('button', {name: 'Import to library', exact: true}).click(); expect((await importResponse).status()).toBe(200);
 const row = hub.getByRole('region', {name: 'Library', exact: true}).locator('.card-row', {hasText: rid});
 await expect(row.getByRole('button', {name: 'Complete from datasheet'})).toBeEnabled();
 await row.getByRole('button', {name: 'Complete from datasheet'}).click();
 const form = page.getByRole('dialog', {name: 'Complete from datasheet', exact: true});
 await expect(form.getByRole('button', {name: 'Preview', exact: true})).toBeDisabled();
 await form.getByLabel('Maximum operating current per MPPT (A)', {exact: true}).fill('26');
 await form.getByLabel('Document', {exact: true}).fill('Fictional browser-test datasheet');
 await form.getByLabel('Page / section', {exact: true}).fill('Synthetic table 1');
 const dryResponse = page.waitForResponse(r => r.url().endsWith(`/component-library/${rid}/complete`) && r.request().postDataJSON().dry_run === true);
 await form.getByRole('button', {name: 'Preview', exact: true}).click(); expect((await dryResponse).status()).toBe(200);
 await expect(form.getByRole('region', {name: 'Completion preview'})).toContainText('Ready for simulation');
 await expect(form.getByRole('region', {name: 'Completion preview'})).toContainText('Fictional browser-test datasheet, Synthetic table 1');
 const before = (await (await request.get(`${API}/api/component-library`)).json()).map((e: any) => e.definition.revision_id);
 expect(before).toEqual([rid]);
 const saveResponse = page.waitForResponse(r => r.url().endsWith(`/component-library/${rid}/complete`) && r.request().postDataJSON().dry_run === false);
 await form.getByRole('button', {name: 'Save completed revision'}).click(); const saved = await saveResponse; expect(saved.status()).toBe(200);
 await expect(form).toBeHidden();
 const entries = (await (await request.get(`${API}/api/component-library?include_hidden=true`)).json());
 const completedEntry = entries.find((e: any) => e.library.completed_from === rid);
 expect(completedEntry).toBeDefined();
 expect(completedEntry.library.readiness.ready).toBe(true);
 expect(completedEntry.library.completion.source).toEqual({document: 'Fictional browser-test datasheet', page_or_section: 'Synthetic table 1'});
 expect(completedEntry.library.completion.fields).toEqual({'mppt_template.max_operating_current_a': 26});
 const completed = completedEntry.definition.revision_id;
 expect(completed).not.toBe(rid);
 await expect(page.locator('.toasts')).toContainText(`Saved completed revision ${completed}`);
 expect(entries.find((e: any) => e.definition.revision_id === rid).library.hidden).toBe(true);
 expect(entries.find((e: any) => e.definition.revision_id === completed).library.completed_from).toBe(rid);
 await hub.getByRole('button', {name: 'Close', exact: true}).click(); await page.keyboard.press('Alt+6');
 await expect(page.locator('.taskpanel').getByRole('combobox', {name: 'Model', exact: true}).locator(`option[value="${completed}"]`)).toContainText('· library');
 await page.locator('.taskpanel').getByRole('combobox', {name: 'Model', exact: true}).selectOption(completed);
 expect((await (await request.get(`${API}/api/projects/${pid}`)).json()).bundle.project.project_id).toBe(pid);
});
