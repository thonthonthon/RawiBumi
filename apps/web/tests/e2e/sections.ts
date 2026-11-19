import type { Locator, Page } from "@playwright/test";

/** UXF1 (U2-16): sections start collapsed unless they hold the active work; open one by its title before using it. */
export async function openSection(scope: Page | Locator, title: string) {
  const toggle = scope.locator(".section__toggle").filter({ hasText: title }).first();
  if ((await toggle.getAttribute("aria-expanded")) === "false") await toggle.click();
}
