import { beforeAll, describe, expect, it } from "vitest";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { buildResultModel, checkResultRules, modelFingerprint, type ResultModel } from "../../src/results/model";
import { CHAPTERS, formatCoordinates, renderReportHtml, type ReportInput } from "../../src/report/template";
import { dateInZone, reportCssText } from "../../src/report/build";
import { formatAddress, geocoderConfig, needsLookup, NOMINATIM, resetGeocoderClock, reverseGeocode, type SiteAddress } from "../../src/site/address";
import type { ProjectView } from "../../src/types";
import { EMPTY_SYSTEM } from "../../src/site/systemInfo";

// F7.1: the owner's directions for the report (22 Oct): a table of contents; a cover with the
// project identity (name, address from the coordinates or typed, no engineering revision data);
// inverter → MPPT → string → modules with azimuth and tilt; a sun-path and shading chapter.

let view: ProjectView;
const t = (key: string, o: Record<string, unknown> = {}) => (key === "results.monthsShort" ? "Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec" : `${key}${Object.keys(o).length ? JSON.stringify(o) : ""}`);

beforeAll(async () => {
  setDemoLatency(0);
  view = await mockApi.project("demo-project");
});

const modelOf = (v: ProjectView): ResultModel => buildResultModel(v, v.bundle.simulation_runs[0], { authority: "DEMO_SYNTHETIC", hourlyAcKw: null });
it("the standalone report embeds osifont rather than depending on the application server", () => {
  expect(reportCssText()).toMatch(/font-family:"osifont";font-weight:400;src:url\(data:font\/woff;base64,/);
});
const report = (over: Partial<ReportInput> = {}, v: ProjectView = view) => {
  const m = over.model ?? modelOf(v);
  return renderReportHtml({
    model: m,
    rules: checkResultRules(m, { strings: v.bundle.electrical_design.strings.length }),
    tier: "free",
    branding: "",
    planFigure: null,
    sldSvg: "<svg></svg>",
    charts: { monthly: "<svg></svg>", waterfall: null, heatmap: null },
    fingerprint: modelFingerprint(m),
    generatedAt: "2026-10-22 08:00 UTC",
    identity: { address: "Jl. Contoh 1 <b>, Bandung", addressAttribution: "© OpenStreetMap contributors", latitude: -6.914744, longitude: 107.60981, elevationM: 768, issuedOn: "2026-10-22", system: EMPTY_SYSTEM },
    css: "",
    t,
    ...over
  });
};
const coverOf = (h: string) => h.slice(h.indexOf("data-cover"), h.indexOf('data-chapter="kpis"'));

describe("F7.1 cover: project identity, no engineering revision data", () => {
  it("shows name, escaped address, coordinates, elevation, timezone and issue date", () => {
    const c = coverOf(report());
    expect(c).toContain("Warehouse rooftop (demo)");
    expect(c).toContain("Jl. Contoh 1 &lt;b&gt;, Bandung");
    expect(c).toContain("6.91474° S, 107.60981° E");
    expect(c).toContain("768 m");
    expect(c).toContain("Asia/Jakarta");
    expect(c).toContain("2026-10-22");
    expect(c).toContain("report.addressCredit");
  });

  it("keeps the run ID, fingerprint and generation time off the cover; they appear once, in Methodology", () => {
    const h = report();
    const m = modelOf(view);
    const fp = modelFingerprint(m);
    const c = coverOf(h);
    for (const x of [m.runId, fp, "08:00 UTC", "report.fingerprint", "report.run"]) expect(c).not.toContain(x);
    const method = h.slice(h.indexOf('data-chapter="method"'), h.indexOf('data-chapter="assumptions"'));
    expect(method).toContain(m.runId);
    expect(method).toContain(fp);
    expect(h.split(fp).length - 1).toBe(1);
  });

  it("says when no address is given, and gives no address credit then", () => {
    const h = report({ identity: { address: null, addressAttribution: "© OpenStreetMap contributors", latitude: 1, longitude: -2, elevationM: null, issuedOn: "2026-10-22", system: EMPTY_SYSTEM } });
    const c = coverOf(h);
    expect(c).toContain("report.addressNone");
    expect(c).not.toContain("report.addressCredit");
    expect(c).toContain("1.00000° N, 2.00000° W");
    expect(c).not.toContain("report.elevation");
  });

  it("names the client only on the branded tier", () => {
    expect(coverOf(report({ tier: "branded", branding: "PT Contoh" }))).toContain("PT Contoh");
    expect(report({ tier: "free", branding: "PT Contoh" })).not.toContain("PT Contoh");
  });

  it("formats coordinates and the issue date in the site's timezone", () => {
    expect(formatCoordinates(-6.2, 106.82)).toBe("6.20000° S, 106.82000° E");
    // 20:00 UTC on 22 Oct is 03:00 on 23 Oct in Jakarta (UTC+7).
    expect(dateInZone(new Date("2026-10-22T20:00:00Z"), "Asia/Jakarta")).toBe("2026-10-23");
    expect(dateInZone(new Date("2026-10-22T20:00:00Z"), "Not/AZone")).toBe("2026-10-22");
  });
});

describe("F7.1 table of contents", () => {
  it("lists every chapter in order, each linked to its section; no page numbers", () => {
    const h = report();
    const toc = h.slice(h.indexOf("data-toc"), h.indexOf("</nav>"));
    const links = [...toc.matchAll(/href="#ch-(\w+)"/g)].map((x) => x[1]);
    expect(links).toEqual([...CHAPTERS]);
    for (const c of CHAPTERS) expect(h).toContain(`id="ch-${c}"`);
    expect(toc).not.toMatch(/target-counter|page/i);
  });
});

describe("F7.1 mapping: one table per inverter, with azimuth and tilt", () => {
  it("gives the demo inverter its model, AC rating, DC capacity and strings with field orientation", () => {
    const m = modelOf(view);
    expect(m.inverters).toHaveLength(1);
    const b = m.inverters[0];
    expect(b.name).toBe("INV-01");
    expect(b.dcKwp).toBeCloseTo((76 * 550) / 1000, 6);
    expect(b.rows.map((r) => r.string)).toEqual(["S1", "S2", "S3", "S4", "S5"]);
    expect(b.rows[0].fields).toEqual([{ field: "Roof A array", azimuthDeg: 0, tiltDeg: 10, moduleOrientation: "portrait" }]);
    expect(b.rows.some((r) => r.mixed)).toBe(false);
    const h = report();
    const inv = h.slice(h.indexOf('data-inverter="INV-01"'));
    expect(inv).toContain("Roof A array");
    expect(inv).toContain("report.orient_portrait");
    expect(h).toContain("report.azimuthNote");
    expect(h).not.toContain("report.mixedNote");
  });

  it("marks a string whose modules face two directions as mixed and lists each field", () => {
    const v: ProjectView = structuredClone(view);
    const f = v.bundle.scene.pv_fields[0];
    v.bundle.scene.pv_fields.push({ ...f, pv_field_id: "fld-b", name: "Roof B array", azimuth_deg: 180, tilt_deg: 15 });
    const s1 = v.bundle.electrical_design.strings.find((s) => s.string_id === "S1")!;
    for (const id of s1.module_instance_ids.slice(8)) v.bundle.scene.module_instances.find((x) => x.module_instance_id === id)!.pv_field_id = "fld-b";
    const row = modelOf(v).inverters[0].rows.find((r) => r.string === "S1")!;
    expect(row.mixed).toBe(true);
    expect(row.fields.map((x) => [x.field, x.azimuthDeg, x.tiltDeg])).toEqual([
      ["Roof A array", 0, 10],
      ["Roof B array", 180, 15]
    ]);
    const h = report({}, v);
    expect(h).toContain("data-mixed");
    expect(h).toContain("Roof B array (180° / 15°)");
    expect(h).toContain("report.mixedNote");
  });

  it("lists inverters with no strings and strings with no MPPT", () => {
    const v: ProjectView = structuredClone(view);
    v.bundle.electrical_design.inverter_instances.push({ inverter_instance_id: "inv-02", inverter_definition_revision_id: "inv-demo-30k", name: "INV-02", enabled: true, mppt_instance_ids: ["mppt-x"] });
    v.bundle.electrical_design.strings.find((s) => s.string_id === "S5")!.target_mppt_instance_id = null;
    const m = modelOf(v);
    expect(m.inverters.map((b) => [b.name, b.rows.length])).toEqual([
      ["INV-01", 4],
      ["INV-02", 0]
    ]);
    expect(m.unassigned).toEqual([{ string: "S5", modules: 14 }]);
    const h = report({}, v);
    expect(h).toContain("report.noStrings");
    expect(h).toContain("report.unassigned");
  });
});

describe("F7.1 sun path and shading", () => {
  it("says the demo run did not quantify shading, and that the sun-path chart waits on the engine", () => {
    const h = report();
    const ch = h.slice(h.indexOf('data-chapter="shading"'), h.indexOf('data-chapter="monthly"'));
    expect(ch).toContain('data-shading="not-quantified"');
    expect(ch).toContain('data-sunpath="pending"');
  });

  it("reports the engine's counterfactual shading loss and its share of unshaded energy", () => {
    const v: ProjectView = structuredClone(view);
    const s = v.bundle.simulation_runs[0].summary_result!;
    s.shading_energy_loss_wh = 2_500_000;
    s.shading_energy_loss_basis = { method_id: "phase59.x", scope: "geometric_near_shading_only", counterfactual_pcc_energy_wh: 50_000_000, electrical_mismatch_included: false };
    const m = modelOf(v);
    expect(m.shading).toEqual({ lossKwh: 2500, unshadedKwh: 50000, scope: "geometric_near_shading_only", mismatchIncluded: false, method: "phase59.x" });
    const h = report({ model: m }, v);
    expect(h).toContain("2,500 kWh");
    expect(h).toContain("5.0 %");
    expect(h).toContain("report.notIncluded");
    expect(h).toContain('data-shading="quantified"');
  });
});

describe("F7.1 site address lookup", () => {
  // A constructed reply in Nominatim's jsonv2 shape (not a recorded one).
  const reply = {
    display_name: "Jalan Contoh, Kelurahan A, Kecamatan B, Kota C, Jawa Barat, 40111, Indonesia",
    address: { road: "Jalan Contoh", house_number: "1", village: "Kelurahan A", city_district: "Kecamatan B", city: "Kota C", state: "Jawa Barat", postcode: "40111", country: "Indonesia" }
  };

  it("formats street, village, district, city, province, postcode and country; falls back to the display name", () => {
    expect(formatAddress(reply)).toBe("Jalan Contoh 1, Kelurahan A, Kecamatan B, Kota C, Jawa Barat, 40111, Indonesia");
    expect(formatAddress({ display_name: " Somewhere " })).toBe("Somewhere");
    expect(formatAddress({ error: "Unable to geocode" })).toBeNull();
    expect(formatAddress({ address: { city: "X", county: "Y", state: "X" } })).toBe("X");
  });

  it("asks the service once per call with the coordinates and language, at most one request per interval", async () => {
    resetGeocoderClock();
    const calls: { url: string; at: number }[] = [];
    const fake = (async (url: string) => {
      calls.push({ url, at: Date.now() });
      return new Response(JSON.stringify(reply), { status: 200 });
    }) as unknown as typeof fetch;
    const cfg = { ...NOMINATIM, minIntervalMs: 200 };
    expect(await reverseGeocode(cfg, -6.914744, 107.60981, "id", fake)).toContain("Kota C");
    await reverseGeocode(cfg, -6.914744, 107.60981, "id", fake);
    expect(calls[0].url).toContain("lat=-6.914744&lon=107.609810");
    expect(calls[0].url).toContain("accept-language=id");
    expect(calls[1].at - calls[0].at).toBeGreaterThanOrEqual(190);
  });

  it("fails plainly on an HTTP error or an empty answer", async () => {
    resetGeocoderClock();
    const cfg = { ...NOMINATIM, minIntervalMs: 0 };
    await expect(reverseGeocode(cfg, 0, 0, "en", (async () => new Response("", { status: 503 })) as unknown as typeof fetch)).rejects.toThrow(/HTTP 503/);
    await expect(reverseGeocode(cfg, 0, 0, "en", (async () => new Response("{}", { status: 200 })) as unknown as typeof fetch)).rejects.toThrow(/no address/);
  });

  it("never replaces a user's edit; re-looks-up a looked-up address when the coordinates move", () => {
    const a = (source: SiteAddress["source"], lat = -6.2, lon = 106.82): SiteAddress => ({ text: "x", source, lat, lon, attribution: null, updatedAt: "" });
    expect(needsLookup(null, -6.2, 106.82)).toBe(true);
    expect(needsLookup(a("lookup"), -6.2, 106.82)).toBe(false);
    expect(needsLookup(a("lookup"), -6.3, 106.82)).toBe(true);
    expect(needsLookup(a("user"), -6.3, 106.82)).toBe(false);
  });

  it("uses Nominatim by default, a configured service if set, and none when switched off", () => {
    expect(geocoderConfig({})).toBe(NOMINATIM);
    expect(geocoderConfig({ VITE_GEOCODER: "off" })).toBeNull();
    expect(geocoderConfig({ VITE_GEOCODER_URL: "https://geo.example/r?lat={lat}&lon={lon}", VITE_GEOCODER_ATTRIBUTION: "© Example" })).toMatchObject({ urlTemplate: "https://geo.example/r?lat={lat}&lon={lon}", attribution: "© Example" });
  });
});
