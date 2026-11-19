import { expect,test as base,type APIRequestContext,type Page } from "@playwright/test";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { readFileSync,mkdirSync,mkdtempSync,rmSync } from "node:fs";
import path from "node:path";
let API=process.env.RAWIBUMI_API;
if(!API||!/^http:\/\/127\.0\.0\.1:\d+$/.test(API)||API.endsWith(':8000'))throw new Error('S12a requires the isolated API, never a user store.');
const ROOT=path.resolve(process.cwd(),'../..');

// Global visibility is intentionally shared by projects. This file gets a separate
// disposable service so its imports/hides cannot race other files' view assertions.
const test=base.extend<{}, {componentLibraryApi:string}>({
 componentLibraryApi:[async({},use)=>{
  mkdirSync(path.join(ROOT,'tmp'),{recursive:true});
  const directory=mkdtempSync(path.join(ROOT,'tmp','s12a-library-live-'));
  const script=`import runpy
from pathlib import Path
runpy.run_path("apps/web/scripts/serve-live-test-api.py",run_name="s12a_test_catalog")
from apps.api.server import create_app
import uvicorn
uvicorn.run(create_app(store_root=Path(${JSON.stringify(directory)})/"projects",library_root=Path(${JSON.stringify(directory)})/"component-library"),host="127.0.0.1",port=0,timeout_keep_alive=75)
`;
  const child=spawn(path.join(ROOT,'.venv/bin/python'),['-c',script],{cwd:ROOT,stdio:['ignore','pipe','pipe']});
  let logs='';
  try{
   API=await new Promise<string>((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error(`S12a isolated API startup timed out: ${logs}`)),20000);
    const data=(chunk:Buffer)=>{logs+=chunk.toString();const address=logs.match(/Uvicorn running on (http:\/\/127\.0\.0\.1:\d+)/);if(address){clearTimeout(timer);resolve(address[1]);}};
    child.stdout.on('data',data);child.stderr.on('data',data);
    child.once('error',error=>{clearTimeout(timer);reject(error);});
    child.once('exit',code=>{clearTimeout(timer);reject(new Error(`S12a isolated API exited ${code}: ${logs}`));});
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

async function open(page:Page,request:APIRequestContext){
 const name=`S12a ${Date.now()} ${Math.random()}`;const r=await request.post(`${API}/api/projects`,{data:{name,latitude_deg:-6.2,longitude_deg:106.8,timezone:'Asia/Jakarta',workspace_mode:'blank_engineering_plane'}});expect(r.status()).toBe(201);
 const pid=(await r.json()).bundle.project.project_id as string;
 const roof=await request.post(`${API}/api/projects/${pid}/surfaces/rectangle`,{data:{name:'Library roof',width_m:12,height_m:10,base_elevation_m:6}});expect(roof.ok()).toBe(true);
 await page.goto('/');await page.locator('.start__row',{hasText:name}).click();await expect(page.locator('.rail')).toBeVisible();await page.keyboard.press('Alt+2');await page.getByRole('button',{name:'Import PAN / template…'}).click();
 const dialog=page.getByRole('dialog',{name:'Import',exact:true});await expect(dialog.getByLabel('Choose a file')).toBeEnabled();return{pid,dialog};
}
function response(page:Page,dry:boolean){return page.waitForResponse(r=>r.request().method()==='POST'&&r.url().includes('/component-library/imports?')&&r.url().includes(`dry_run=${dry}`));}

test('Jinko preview and global import refresh the module selector; a field pins that exact revision',async({page,request})=>{
 const{pid,dialog}=await open(page,request);
 await dialog.getByLabel('Choose a file').setInputFiles(path.join(ROOT,'tests/fixtures/panond/manufacturer/JKM550M-72HL4-V_SGS_6079M3.PAN'));
 const preview=response(page,true);await dialog.getByRole('button',{name:'Detect and preview'}).click();const p=await preview;expect(p.status()).toBe(200);
 const section=dialog.getByRole('region',{name:'Component preview'});await expect(section).toContainText('Jinkosolar JKM550M-72HL4-V');const rid=(await section.locator('code').first().innerText()).trim();expect(rid).toMatch(/^lib-mod-.*-r[1-9][0-9]*$/);await expect(section.locator('[data-component-readiness]')).toHaveText('Ready for simulation');await expect(section.getByRole('table')).toContainText('V/°C');await expect(section.getByRole('table')).toContainText('not in file');
 const importing=response(page,false);await dialog.getByRole('button',{name:'Import to library',exact:true}).click();expect((await importing).status()).toBe(200);await expect(page.locator('.toasts')).toContainText(rid);
 await dialog.getByRole('button',{name:'Close',exact:true}).click();await page.keyboard.press('Alt+4');const panel=page.locator('.taskpanel'),select=panel.getByRole('combobox',{name:'Module',exact:true});await expect(select.locator(`option[value="${rid}"]`)).toContainText('· library');await select.selectOption(rid);
 const fill=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/pv-fields'));
 await panel.getByRole('button',{name:'Apply fill',exact:true}).click();expect((await fill).status()).toBe(200);
 const project=await(await request.get(`${API}/api/projects/${pid}`)).json();expect(project.bundle.scene.module_instances.length).toBeGreaterThan(0);expect(project.bundle.scene.pv_fields[0].module_definition_revision_id).toBe(rid);expect(project.bundle.pinned_components.modules).toHaveProperty(rid);
 const beforeCard=await panel.locator('.card-row').innerText();
 await page.keyboard.press('Alt+2');await page.getByRole('button',{name:'Import PAN / template…'}).click();await expect(dialog.getByLabel('Choose a file')).toBeEnabled();
 const libraryRow=dialog.getByRole('region',{name:'Library',exact:true}).locator('.card-row',{hasText:rid});
 await libraryRow.getByRole('button',{name:'Hide',exact:true}).click();const hiding=page.getByRole('alertdialog',{name:'Hide library revision?',exact:true});await expect(hiding).toContainText(rid);
 await hiding.getByRole('button',{name:'Cancel',exact:true}).click();expect((await(await request.get(`${API}/api/catalog`)).json()).modules.some((m:{revision_id:string})=>m.revision_id===rid)).toBe(true);
 await libraryRow.getByRole('button',{name:'Hide',exact:true}).click();const hidden=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith(`/component-library/${rid}/hide`));await hiding.getByRole('button',{name:'Hide',exact:true}).click();expect((await hidden).status()).toBe(200);await expect(hiding).toBeHidden();
 try {
  const global=await(await request.get(`${API}/api/catalog`)).json();expect(global.modules.some((m:{revision_id:string})=>m.revision_id===rid)).toBe(false);
  await dialog.getByRole('button',{name:'Close',exact:true}).click();await page.keyboard.press('Alt+4');await expect.poll(()=>panel.locator('.card-row').innerText()).toBe(beforeCard);
  await panel.getByRole('button',{name:'Re-fill',exact:true}).click();await panel.getByLabel('Tilt').fill('15');await expect(panel.getByRole('button',{name:'Apply re-fill',exact:true})).toBeEnabled();
  const refill=page.waitForResponse(r=>r.request().method()==='PATCH'&&r.url().includes('/pv-fields/')&&r.request().postDataJSON().dry_run===true);await panel.getByRole('button',{name:'Apply re-fill',exact:true}).click();expect((await refill).status()).toBe(200);
  const review=page.getByRole('alertdialog',{name:'Preview re-fill',exact:true});await expect(review).toBeVisible();await review.getByRole('button',{name:'Cancel',exact:true}).click();
 } finally {expect((await request.post(`${API}/api/component-library/${rid}/unhide`)).ok()).toBe(true);}
});

test('synthetic cp1252 Huawei previews as layout only; legacy and binary PANs get the plain D11 refusal',async({page,request})=>{
 const{dialog}=await open(page,request);
 const source=readFileSync(path.join(ROOT,'tests/fixtures/panond/manufacturer/Huawei_Sun2000_100KTL_M1.OND'));
 // Entire variant is generated here from the existing repository fixture; no private file is used.
 const synthetic=Buffer.concat([Buffer.from('PVObject_=pvGInverter\n  Comment=Synthetic degree '),Buffer.from([0xb0]),source.subarray('PVObject_=pvGInverter'.length)]);
 await dialog.getByLabel('Choose a file').setInputFiles({name:'synthetic-degree.ond',mimeType:'application/octet-stream',buffer:synthetic});
 const preview=response(page,true);await dialog.getByRole('button',{name:'Detect and preview'}).click();expect((await preview).status()).toBe(200);
 const section=dialog.getByRole('region',{name:'Component preview'});await expect(section.locator('[data-component-readiness]')).toHaveText('Layout only');await expect(section.locator('[data-rule-id="INVERTER_AC_FREQUENCY_NOT_SPECIFIED"]')).toContainText('does not state its nominal AC frequency');await expect(section).toContainText('maximum operating current per MPPT is not in the file');await expect(section.getByRole('table')).toContainText('European efficiency');await expect(section.getByRole('table')).toContainText('98.82');
 const rid=(await section.locator('code').first().innerText()).trim();const importing=response(page,false);await dialog.getByRole('button',{name:'Import to library',exact:true}).click();const commit=await importing;expect(commit.status()).toBe(200);await expect(page.locator('.toasts')).toContainText(rid);
 for(const bytes of [Buffer.from('pvModule;SYNTHETIC LEGACY'),Buffer.from([0xff,0x00,0x01])]){
  await dialog.getByLabel('Choose a file').setInputFiles({name:'synthetic-legacy.pan',mimeType:'application/octet-stream',buffer:bytes});const refused=response(page,true);await dialog.getByRole('button',{name:'Detect and preview'}).click();const r=await refused;expect(r.status()).toBe(422);expect((await r.json()).detail.code).toBe('legacy_binary_pan_unsupported');await expect(dialog.getByRole('alert')).toContainText('Export it again from PVsyst 6 or later as a text file');await expect(dialog.getByRole('button',{name:'Import to library',exact:true})).toHaveCount(0);
 }
 await dialog.getByRole('button',{name:'Close',exact:true}).click();await page.keyboard.press('Alt+6');await expect(page.locator('.taskpanel').getByRole('combobox',{name:'Model',exact:true}).locator(`option[value="${rid}"]`)).toContainText('· library · layout only');
});
