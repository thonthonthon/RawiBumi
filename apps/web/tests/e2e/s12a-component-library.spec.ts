import { expect,test } from "@playwright/test";
test("component imports honestly need the real engine; weather is enabled and geometry retains its badge",async({page})=>{
 const requests:string[]=[];page.on("request",r=>{if(r.url().includes('/api/component-library'))requests.push(r.url());});
 await page.goto('/');await page.locator('.start__row').first().click();await expect(page.locator('.rail')).toBeVisible();await page.keyboard.press('Alt+2');await page.getByRole('button',{name:'Import PAN / template…'}).click();
 const dialog=page.getByRole('dialog',{name:'Import',exact:true});const picker=dialog.getByLabel('Choose a file');await expect(picker).toBeEnabled();
 await picker.setInputFiles({name:'synthetic.pan',mimeType:'application/octet-stream',buffer:Buffer.from('PVObject_=pvModule\nEnd of PVObject pvModule\n')});
 await dialog.getByRole('button',{name:'Detect and preview'}).click();await expect(dialog.getByRole('alert')).toContainText('Importing components needs the engine');await expect(dialog.getByRole('button',{name:'Import to library',exact:true})).toHaveCount(0);await expect(dialog.locator('.card-row')).toHaveCount(0);await expect(dialog.locator('.notwired')).toHaveCount(0);
 await dialog.getByRole('button',{name:'Weather',exact:true}).click();await expect(dialog.locator('.notwired')).toHaveCount(0);await expect(dialog.getByRole('button',{name:'Detect and preview'})).toBeDisabled();expect(requests).toEqual([]);
 await dialog.getByRole('button',{name:'Geometry',exact:true}).click();await expect(dialog.locator('.notwired')).toHaveCount(1);await expect(dialog.getByRole('button',{name:'Detect and preview'})).toBeDisabled();expect(requests).toEqual([]);
});
