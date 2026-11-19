import { expect, test } from "@playwright/test";

const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000"))
  throw new Error("USE3C requires a disposable API on a checked free port, never port 8000.");

interface ModuleRow { table_index: number; metadata: { table_row_offset: number }; transform: { position_y_m: number } }
const smallerSide = (modules: ModuleRow[]) => {
  const tables = new Map<number, ModuleRow[]>();
  for (const m of modules) tables.set(m.table_index, [...(tables.get(m.table_index) ?? []), m]);
  const rows = [...tables.values()].map((ms) => ({ y: Math.max(...ms.map((m) => m.transform.position_y_m)),
    rows: new Set(ms.map((m) => m.metadata.table_row_offset)).size })).sort((a, b) => a.y - b.y);
  return rows.find((r) => r.rows === 1)!.y === rows[0].y ? "back" : "front";
};

test("two-row browser fill and re-fill move the smaller table between front and back", async ({ page, request }) => {
  const name = `USE3C ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8,
    timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(created.ok()).toBe(true);
  const id: string = (await created.json()).bundle.project.project_id;
  const url = `${API}/api/projects/${id}`;
  try {
    const roof = await request.post(url + "/surfaces/rectangle", { data: { name: "USE3C roof", width_m: 8, height_m: 14, base_elevation_m: 6 } });
    expect(roof.ok()).toBe(true);
    await page.addInitScript(() => window.localStorage.setItem("rawibumi.language", "en"));
    await page.goto("/"); await page.locator(".start__row", { hasText: name }).click();
    await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+4");
    const panel = page.locator(".taskpanel");
    await panel.getByLabel("Field name").fill("USE3C array");
    await panel.getByLabel("Rows per table", { exact: true }).fill("2");
    await panel.getByLabel("Tilt").fill("0");
    await panel.getByLabel("Leftover depth").selectOption("smaller_table_front");
    const filled = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/pv-fields`) && r.request().method() === "POST");
    await panel.getByRole("button", { name: "Apply fill", exact: true }).click();
    const response = await filled; expect(response.ok()).toBe(true);
    const body = response.request().postDataJSON();
    const before = (await response.json()).bundle;
    expect(body.rows_per_table).toBe(2); expect(body.leftover_depth).toBe("smaller_table_front");
    const field = before.scene.pv_fields[0];
    // The API preview independently re-packs the committed request; the browser's displayed count must agree.
    const preview = await request.patch(url + `/pv-fields/${field.pv_field_id}`, { data: { ...body, support_surface_id: undefined, dry_run: true } });
    expect(preview.ok()).toBe(true);
    const expected = (await preview.json()).module_count_after;
    expect(before.scene.module_instances).toHaveLength(expected);
    await expect(panel.locator(".card-row", { hasText: "USE3C array" })).toContainText(String(expected));
    expect(smallerSide(before.scene.module_instances)).toBe("front");
    await panel.getByRole("button", { name: "Re-fill", exact: true }).click();
    await panel.getByLabel("Leftover depth").selectOption("smaller_table");
    await panel.getByRole("button", { name: "Apply re-fill", exact: true }).click();
    const dialog = page.getByRole("alertdialog", { name: "Preview re-fill", exact: true });
    await dialog.getByRole("button", { name: "Confirm re-fill", exact: true }).click();
    await expect(dialog).toBeHidden();
    const after = (await (await request.get(url)).json()).bundle;
    expect(after.scene.pv_fields[0].table_configuration.leftover_depth).toBe("smaller_table");
    expect(smallerSide(after.scene.module_instances)).toBe("back");
  } finally {
    expect((await request.delete(url, { params: { confirm: id } })).ok()).toBe(true);
  }
});
