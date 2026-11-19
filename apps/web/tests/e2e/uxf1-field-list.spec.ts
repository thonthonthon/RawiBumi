import { expect, test } from "@playwright/test";

// UXF1 (U2-7): at the narrowest task panel, each PV field card stays at two lines (name with actions, then the summary)
// with no horizontal overflow; details fold away and open for the field being re-filled.
test("PV field cards stay compact at the narrowest task panel", async ({ page }) => {
  await page.goto("/"); await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+4");
  const panel = page.locator(".taskpanel");
  const card = panel.locator("[data-pv-field-card]").first();
  await expect(card).toBeVisible();
  // Drag the task panel's splitter left past its minimum (320 px default, 260 px minimum); it stops at the minimum.
  const splitter = page.locator(".splitter:not(.splitter--h)").first();
  const box = (await splitter.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down();
  await page.mouse.move(box.x - 120, box.y + box.height / 2, { steps: 8 }); await page.mouse.up();
  await expect.poll(async () => Math.round((await panel.boundingBox())!.width)).toBeLessThanOrEqual(262);
  expect((await panel.boundingBox())!.width).toBeGreaterThanOrEqual(255);
  expect(await panel.locator("[data-pv-field-card]").count()).toBeGreaterThan(0);

  for (const one of await panel.locator("[data-pv-field-card]").all()) {
    const m = await one.evaluate((el) => {
      const r = (q: string) => el.querySelector(q)!.getBoundingClientRect();
      const line = parseFloat(getComputedStyle(el.querySelector(".card-row__summary")!).lineHeight) || 16;
      const buttons = [...el.querySelectorAll(".card-row__actions button")].map((b) => Math.round(b.getBoundingClientRect().top));
      return { overflow: el.scrollWidth - el.clientWidth, name: r(".card-row__name").height, summary: r(".card-row__summary").height,
        line, buttonRows: new Set(buttons).size, summaryBelowName: r(".card-row__summary").top >= r(".card-row__name").bottom - 1,
        detailsOpen: (el.querySelector(".card-row__more") as HTMLDetailsElement).open };
    });
    expect(m.overflow).toBeLessThanOrEqual(0);
    expect(m.buttonRows).toBe(1); // the actions never wrap
    expect(m.summary).toBeLessThan(m.line * 1.6); // one summary line
    expect(m.name).toBeLessThan(m.line * 2); // one name line
    expect(m.summaryBelowName).toBe(true);
    expect(m.detailsOpen).toBe(false);
  }
  // Details hold the rest and open on demand.
  await card.locator(".card-row__more > summary").click();
  await expect(card.locator(".card-row__more")).toContainText("Roof");
});
