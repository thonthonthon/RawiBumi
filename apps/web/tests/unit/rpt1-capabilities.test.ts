import { afterEach, expect, it } from "vitest";
import { can, setEntitlementSource, type Feature } from "../../src/platform/entitlements";
const aliases = [
  ["core.export.csv-basic","export.csv.basic"], ["export.csv","export.csv.basic"],
  ["core.export.pdf-native","export.report.protected_pdf"], ["export.report.native_pdf","export.report.protected_pdf"],
  ["export.csv-string-level","export.csv.engineering"], ["report.branded","export.report.custom_branding"]
] as const;
afterEach(() => setEntitlementSource(null));
it("keeps aliases equal to their targets with the self-hosted source and legacy custom sources", () => {
  for (const custom of [null, (f: Feature) => f !== "core.export.csv-basic", (f: Feature) => f === "report.branded"]) {
    setEntitlementSource(custom);
    for (const [alias,target] of aliases) expect(can(alias as Feature)).toBe(can(target as Feature));
  }
});
it("keeps Free capabilities on, Pro off, and retired raster off even with an allow-all source", () => {
  expect(can("export.csv.basic" as Feature)).toBe(true);
  expect(can("export.report.protected_pdf" as Feature)).toBe(true);
  for (const id of ["export.csv.engineering","export.report.custom_branding"]) expect(can(id as Feature)).toBe(false);
  setEntitlementSource(() => true);
  expect(can("export.report.raster_pdf" as Feature)).toBe(false);
});
it("preserves the existing legacy callback denial for canonical CSV calls", () => {
  setEntitlementSource(f => f !== "core.export.csv-basic");
  expect(can("export.csv.basic" as Feature)).toBe(false);
});
it("makes a denial of any canonical ID or alias deny the whole family, while allow-all allows every active name", () => {
  for (const target of new Set(aliases.map(([,target]) => target))) {
    const family: Feature[] = [target, ...aliases.filter(([,canonical]) => canonical === target).map(([alias]) => alias)];
    for (const denied of family) {
      setEntitlementSource(feature => feature !== denied);
      for (const name of family) expect(can(name), `${denied} must deny ${name}`).toBe(false);
      expect(can("core.design")).toBe(true);
    }
  }
  setEntitlementSource(() => true);
  for (const name of new Set(aliases.flat())) expect(can(name)).toBe(true);
  expect(can("export.report.raster_pdf")).toBe(false);
});
