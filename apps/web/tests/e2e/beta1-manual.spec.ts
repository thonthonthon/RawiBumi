import { expect, test } from "@playwright/test";

// BETA1: the Manual link opens the built-in manual (not the app again), in English with a link to the Indonesian
// edition; steps are numbered in rail order (Systems is step 5, with its Alt+5 shortcut).
test("the Manual link opens the English manual, which links to the Indonesian one", async ({ page, context }) => {
  await page.goto("/");
  const [manual] = await Promise.all([context.waitForEvent("page"), page.getByRole("link", { name: "Manual" }).click()]);
  await manual.waitForLoadState();
  await expect(manual).toHaveTitle("RawiBumi manual");
  await expect(manual.getByRole("heading", { name: "8. Step 5 · Systems (Alt+5)" })).toBeVisible();
  await expect(manual.getByRole("heading", { name: "9. Step 6 · Electrical (Alt+6)" })).toBeVisible();
  await manual.getByRole("link", { name: "Bahasa Indonesia" }).click();
  await expect(manual).toHaveTitle("Panduan RawiBumi");
  await expect(manual.getByRole("heading", { name: "8. Langkah 5 · Sistem (Alt+5)" })).toBeVisible();
  await manual.getByRole("link", { name: "English" }).click();
  await expect(manual).toHaveTitle("RawiBumi manual");
});
