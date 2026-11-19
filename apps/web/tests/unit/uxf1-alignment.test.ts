import { expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import "../../src/i18n";
import { legacyFieldInput, legacyRefillRequest, pvFieldChanges, type FillZoneRequest, type StoredPvField } from "../../src/engine/layout";
import { AlignmentPicker, FILL_DEFAULTS, requestOf } from "../../src/panels/LayoutPanel";

// UXF1 (U2-6): nine-point alignment reaches the engine only when chosen, and a re-fill sends only a changed one.
const module = { width_m: 1.1, height_m: 2.3 };
const request = (extra: Partial<FillZoneRequest> = {}): FillZoneRequest =>
  ({ ...requestOf({ ...FILL_DEFAULTS, surface: "roof", module: "mod-r1" }, 4), ...extra });
const field = (packing: Record<string, unknown>): StoredPvField => ({
  pv_field_id: "f1", name: "Roof array", support_surface_id: "roof", module_definition_revision_id: "mod-r1",
  orientation: "portrait", azimuth_deg: 0, tilt_deg: 10, mounting_height_m: 0.2, module_gap_x_m: 0.02, module_gap_y_m: 0.02,
  row_pitch_m: 2.8651, setback_configuration: { perimeter_setback_m: 0.3, obstacle_setback_m: 0.3 }, packing_parameters: packing
} as unknown as StoredPvField);

it("a default fill sends exactly the request it sent before UXF1", () => {
  const input = legacyFieldInput(request(), module).input!;
  expect(input).not.toHaveProperty("row_alignment");
  expect(input).not.toHaveProperty("depth_alignment");
});

it("a chosen alignment is sent in both directions", () => {
  const input = legacyFieldInput(request({ row_alignment: "end", depth_alignment: "center" }), module).input!;
  expect(input).toMatchObject({ row_alignment: "end", depth_alignment: "center" });
  expect(legacyFieldInput(request({ row_alignment: "start", depth_alignment: "start" }), module).input)
    .toMatchObject({ depth_alignment: "start" });
});

it("a re-fill reads the stored alignment and sends only a changed one", () => {
  const stored = field({ row_alignment: "center", depth_alignment: "end" });
  const refill = legacyRefillRequest(stored, module, 4)!;
  expect(refill).toMatchObject({ row_alignment: "center", depth_alignment: "end" });
  expect(pvFieldChanges(refill, stored, module).changes).toEqual({});
  expect(pvFieldChanges({ ...refill, depth_alignment: "start" }, stored, module).changes).toEqual({ depth_alignment: "start" });
  expect(pvFieldChanges({ ...refill, row_alignment: "start" }, stored, module).changes).toEqual({ row_alignment: "start" });
  const old = legacyRefillRequest(field({ row_alignment: "start" }), module, 4)!;
  expect(old.depth_alignment).toBeNull();
  expect(pvFieldChanges(old, field({ row_alignment: "start" }), module).changes).toEqual({});
});

it("the picker has nine labelled cells, front on top, and marks the chosen one", () => {
  const html = renderToStaticMarkup(createElement(AlignmentPicker, { row: "end", depth: "end", onChange: () => undefined }));
  const cells = [...html.matchAll(/aria-pressed="(true|false)" aria-label="([^"]+)"/g)].map((m) => [m[2], m[1]]);
  expect(cells.map(([label]) => label)).toEqual(["Front left", "Front centre", "Front right", "Middle left", "Middle centre",
    "Middle right", "Back left", "Back centre", "Back right"]);
  expect(cells.filter(([, pressed]) => pressed === "true")).toEqual([["Front right", "true"]]);
  expect(html.indexOf("Front (low edge)")).toBeLessThan(html.indexOf("Back (high edge)"));
  const automatic = renderToStaticMarkup(createElement(AlignmentPicker, { row: "start", depth: null, onChange: () => undefined }));
  expect(automatic).not.toContain('aria-pressed="true"');
  expect(automatic).toContain("Rows placed for the most modules");
});
