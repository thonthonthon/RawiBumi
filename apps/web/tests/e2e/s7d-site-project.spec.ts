import { expect, test } from "@playwright/test";
import { openSection } from "./sections";

test("rename and delete require explicit project-list actions and an exact name", async ({ page }) => {
  await page.goto("/");
  const row = page.locator(".tbl--projects tbody tr").first();
  await row.getByRole("button", { name: "Rename", exact: true }).click();
  const rename = page.getByRole("dialog", { name: "Rename", exact: true });
  await rename.getByLabel("Project name", { exact: true }).fill("  S7d renamed demo  ");
  await rename.getByRole("button", { name: "Rename", exact: true }).click();
  await expect(rename).toBeHidden(); await expect(row).toContainText("S7d renamed demo");
  await row.getByRole("button", { name: "Delete", exact: true }).click();
  const deletion = page.getByRole("alertdialog", { name: "Delete", exact: true });
  await expect(deletion).toContainText("permanently"); await expect(deletion).toContainText("Shared weather snapshots are kept");
  const confirm = deletion.getByRole("button", { name: "Delete", exact: true }); await expect(confirm).toBeDisabled();
  await deletion.getByLabel("Type the exact project name").fill("S7d renamed demo "); await expect(confirm).toBeDisabled();
  await deletion.getByLabel("Type the exact project name").fill("S7d renamed demo"); await expect(confirm).toBeEnabled();
  await confirm.click(); await expect(deletion).toBeHidden(); await expect(page.locator(".tbl--projects tbody tr")).toHaveCount(0);
});

test("bad start coordinates stay inline and the rest of the app works", async ({ page }) => {
  const errors: string[] = []; page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/"); await page.getByLabel("Latitude", { exact: false }).fill("123");
  await expect(page.getByRole("alert")).toContainText("Latitude must be greater");
  await expect(page.getByRole("button", { name: "Create project", exact: true })).toBeDisabled();
  await expect(page.locator(".start__projects")).toBeVisible();
  await page.locator(".start__row").first().click(); await expect(page.locator(".rail")).toBeVisible(); expect(errors).toEqual([]);
});

test("site edits validate inline, reset, and persist name and coordinates in demo", async ({ page }) => {
  await page.goto("/"); await page.locator(".start__row").first().click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+1");
  const p = page.locator(".taskpanel");
  await p.getByLabel("Latitude", { exact: true }).fill("90"); await expect(p.getByRole("alert")).toContainText("poles");
  await expect(p.getByRole("button", { name: "Apply", exact: true })).toBeDisabled();
  await p.getByRole("button", { name: "Reset", exact: true }).click();
  await p.getByLabel("Site name", { exact: true }).fill("Renamed site"); await p.getByLabel("Latitude", { exact: true }).fill("-7.25");
  await p.getByRole("button", { name: "Apply", exact: true }).click();
  const dialog = page.getByRole("alertdialog", { name: "Clear pinned weather?" });
  // The seeded demo includes synthetic weather, so the same confirmation is required.
  await expect(dialog).toBeVisible(); await dialog.getByRole("button", { name: "Clear selection and apply" }).click();
  await expect(dialog).toBeHidden(); await expect(p.getByLabel("Site name", { exact: true })).toHaveValue("Renamed site");
  await expect(p.getByLabel("Latitude", { exact: true })).toHaveValue("-7.25");
});

test("losses expose editable demo defaults and sub-hourly timesteps stay disabled", async ({ page }) => {
  await page.goto("/"); await page.locator(".start__row").first().click(); await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+8");
  await openSection(page, "Losses");
  const losses = page.locator(".section", { has: page.getByRole("button", { name: "Losses", exact: true }) });
  await expect(losses).toContainText("Applied by the engine"); await expect(losses).toContainText("Demo values (illustrative)");
  await expect(losses).toContainText("Module quality: from the pinned module definition (default 0 %; negative = gain)");
  await expect(losses.getByLabel("Soiling month 1 (%)", { exact: true })).toBeEditable();
  await expect(losses.getByLabel("Soiling month 1 (%)", { exact: true })).toHaveValue("3");
  await expect(losses.getByRole("button", { name: "Save losses", exact: true })).toBeDisabled();
  await expect(losses.getByRole("button", { name: "Reset to recommended defaults", exact: true })).toBeDisabled();
  await page.keyboard.press("Alt+7");
  for (const name of ["1", "5", "15"]) await expect(page.getByRole("radio", { name, exact: true })).toBeDisabled();
  await expect(page.getByRole("radio", { name: "60 min (engine)", exact: true })).toHaveAttribute("aria-checked", "true");
});
