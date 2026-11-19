import { expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import "../../src/i18n";
import { acSegmentDraft, acSegmentValue, AcSegmentEditor, CABLE_SIZES_MM2 } from "../../src/panels/LossesPanel";
import type { AcWiringSegment } from "../../src/types";

// UXF1 (U2-5): the cable cross-section is chosen from the IEC 60228 sizes; a saved non-standard value stays as custom.
const render = (area: string) => renderToStaticMarkup(createElement(AcSegmentEditor, {
  name: "Plant", draft: { ...acSegmentDraft(), mode: "cable", length: "40", area }, onChange: () => undefined, plant: true
}));
const options = (html: string) => [...html.matchAll(/<option value="([^"]*)"[^>]*>([^<]*)<\/option>/g)].map((m) => [m[1], m[2]]);
const areaOptions = (html: string) => options(html.slice(html.indexOf("Cross-section per phase")));

it("offers exactly the standard sizes, with no free number box for the cross-section", () => {
  expect([...CABLE_SIZES_MM2]).toEqual([1.5, 2.5, 4, 6, 10, 16, 25, 35, 50, 70, 95, 120, 150, 185, 240, 300, 400, 500, 630]);
  const html = render("120");
  const sizes = areaOptions(html).slice(0, CABLE_SIZES_MM2.length).map(([value]) => Number(value));
  expect(sizes).toEqual([...CABLE_SIZES_MM2]);
  expect(html).toMatch(/<option value="120" selected="">120<\/option>/);
});

it("a new cable asks for a size, and a saved non-standard size is kept as custom and unchanged", () => {
  expect(areaOptions(render(""))[0]).toEqual(["", "Choose a size"]);
  const segment = { mode: "cable", length_one_way_m: 40, cross_section_per_phase_mm2: 7, material: "copper", line_voltage_v: 400,
    conductor_temperature_c: 50, phase_system: "balanced_three_phase", power_factor: 1 } as unknown as AcWiringSegment;
  const draft = acSegmentDraft(segment);
  expect(draft.area).toBe("7");
  const html = render(draft.area);
  expect(areaOptions(html)[0]).toEqual(["7", "7 (custom)"]);
  expect(html).toMatch(/<option value="7" selected="">7 \(custom\)<\/option>/);
  expect(acSegmentValue(draft)).toMatchObject({ cross_section_per_phase_mm2: 7 });
});
