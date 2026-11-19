import {expect,test} from '@playwright/test';
test('weather import is available in the hub and honestly needs the engine in demo',async({page})=>{
 await page.goto('/');await page.locator('.start__row').first().click();await expect(page.locator('.rail')).toBeVisible();await page.keyboard.press('Alt+7');
 await page.getByRole('button',{name:'Import TMY3 / EPW / MET CSV…'}).click();const dialog=page.getByRole('dialog',{name:'Import',exact:true});
 await expect(dialog.locator('.notwired')).toHaveCount(0);
 await dialog.getByLabel('Choose a file').setInputFiles({name:'synthetic.epw',mimeType:'application/octet-stream',buffer:Buffer.from('Explicitly fictional weather test')});
 await expect(dialog.getByRole('button',{name:'Detect and preview'})).toBeEnabled();await dialog.getByRole('button',{name:'Detect and preview'}).click();
 await expect(dialog.getByRole('alert')).toContainText('Importing weather files needs the engine');
 await expect(dialog.getByRole('button',{name:'Use this weather for the project'})).toHaveCount(0);
});
