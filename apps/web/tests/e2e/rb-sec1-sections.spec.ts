import { expect, test, type Page } from "@playwright/test";
import { en } from "../../src/i18n/en";
import { id } from "../../src/i18n/id";

async function start(page: Page) {
  await page.goto("/"); await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
}
const headings = (page: Page) => page.locator(".taskpanel .pane__body > .section > .section__head > .section__toggle, .taskpanel [data-systems-panel] > .section > .section__head > .section__toggle");
for (const [language, m] of [["en", en], ["id", id]] as const) {
  test(`RB-SEC1 all nine steps: ${language} titles, order and open defaults`, async ({ page }) => {
    await page.addInitScript(lang => localStorage.setItem("rawibumi.language", lang), language);
    await start(page);
    const s = m.sections;
    const steps: Array<Array<[string, boolean]>> = [
      [[s.location, true], [s.installation, false], [s.background, false]],
      [[m.use3.inProject, true], [m.use3.library, false]],
      [[m.tools.title, true], [s.layers, true], [m.snap.title, false]],
      [[m.layout.fields, true], [s.selection, false]],
      [[m.systems.inverters, true], [m.systems.buildings, true], [s.checks, false]],
      [[m.systems.inverters, true], [s.strings, true], [m.electrical.selectionTitle, false], [s.rules, false]],
      [[s.weather, true]],
      [[s.losses, true], [s.opticsThermal, false], [m.sky1.title, false], [s.loadExport, false]],
      [[m.s7a.warnings, true], [s.preflight, true], [s.execution, false], [s.history, false]]
    ];
    for (const [index, expected] of steps.entries()) {
      // Each step's defaults are independent of a same-named section visited earlier.
      await page.evaluate(() => {
        for (const key of Object.keys(localStorage)) if (key.startsWith("rawibumi.section.")) localStorage.removeItem(key);
      });
      await page.keyboard.press(`Alt+${index + 1}`);
      await expect(headings(page)).toHaveText(expected.map(([title]) => new RegExp(`${title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`)));
      for (const [i, [, open]] of expected.entries()) await expect(headings(page).nth(i)).toHaveAttribute("aria-expanded", String(open));
    }
  });
}

test("Library opens only for an empty project and retains the user's choice", async ({ page }) => {
  await start(page); await page.keyboard.press("Alt+2");
  const library = page.locator(".taskpanel").getByRole("button", { name: "Library", exact: true });
  await expect(library).toHaveAttribute("aria-expanded", "false");
  await page.evaluate(async () => {
    const { uiStore } = await import("/src/state/store.tsx");
    const view = structuredClone(uiStore.getState().state.view!);
    view.bundle.scene.module_instances = [];
    view.bundle.electrical_design.inverter_instances = [];
    uiStore.getState().dispatch({ type: "setView", view });
  });
  await expect(library).toHaveAttribute("aria-expanded", "true");
  await library.click();
  await page.keyboard.press("Alt+3"); await page.keyboard.press("Alt+2");
  await expect(library).toHaveAttribute("aria-expanded", "false");
});
for (const step of [4, 6]) test(`Selection in step ${step} follows selection until explicitly toggled`, async ({ page }) => {
  await start(page); await page.keyboard.press(`Alt+${step}`);
  const selection = page.locator(".taskpanel").getByRole("button", { name: "Selection", exact: true });
  const select = (active: boolean) => page.evaluate(async active => {
    const { uiStore } = await import("/src/state/store.tsx");
    const store = uiStore.getState();
    store.dispatch({ type: "select", ids: active ? [store.state.modules[0].id] : [] });
  }, active);
  await expect(selection).toHaveAttribute("aria-expanded", "false");
  await select(true); await expect(selection).toHaveAttribute("aria-expanded", "true");
  await select(false); await expect(selection).toHaveAttribute("aria-expanded", "false");
  await select(true); await selection.click();
  await select(false); await select(true);
  await expect(selection).toHaveAttribute("aria-expanded", "false");
  await selection.click(); await select(false);
  await expect(selection).toHaveAttribute("aria-expanded", "true");
});
