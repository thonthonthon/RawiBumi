import {expect, test} from "@playwright/test";
test("datasheet completion is honestly unavailable in the demo library", async ({page}) => {
 await page.goto('/'); await page.locator('.start__row').first().click(); await expect(page.locator('.rail')).toBeVisible();
 await page.keyboard.press('Alt+2'); await page.getByRole('button', {name: 'Import PAN / template…'}).click();
 const dialog = page.getByRole('dialog', {name: 'Import', exact: true});
 await expect(dialog.getByRole('alert')).toContainText('needs the engine');
 await expect(dialog.getByRole('button', {name: 'Complete from datasheet', exact: true})).toHaveCount(0);
 await expect(dialog.getByRole('button', {name: 'Save completed revision'})).toHaveCount(0);
});
