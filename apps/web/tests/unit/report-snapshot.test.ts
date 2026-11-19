import { beforeAll, describe, expect, it } from "vitest";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { modelFingerprint, buildResultModel } from "../../src/results/model";
import { canonicalSerialize, createReportSnapshot, reportInputFingerprint, type ReportSnapshotInput } from "../../src/report/snapshot";
import { EMPTY_SYSTEM } from "../../src/site/systemInfo";
import type { SiteAddress } from "../../src/site/address";
import type { Entity, ModuleShape } from "../../src/state/store";
import type { ProjectView } from "../../src/types";

let view: ProjectView;
const address: SiteAddress = { text: "Jalan Contoh 1", attribution: "© OpenStreetMap contributors", source: "lookup", lat: -6.2, lon: 106.82, updatedAt: "2026-10-25T00:00:00Z" };
const input = (over: Partial<ReportSnapshotInput> = {}): ReportSnapshotInput => ({
  view,
  entities: [],
  modules: [],
  runId: view.bundle.simulation_runs[0].simulation_run_id,
  authority: "DEMO_SYNTHETIC",
  hourlyAcKw: null,
  tier: "free",
  branding: "",
  address,
  language: "en",
  t: (key) => key,
  ...over
});

beforeAll(async () => {
  setDemoLatency(0);
  view = await mockApi.project("demo-project");
});

describe("report canonical serialization", () => {
  it("sorts object keys at every depth, including objects inside arrays", () => {
    const a = { z: [{ b: 2, a: { d: 4, c: 3 } }], a: { "2": 2, "10": 10 } };
    const b = { a: { "10": 10, "2": 2 }, z: [{ a: { c: 3, d: 4 }, b: 2 }] };
    expect(canonicalSerialize(a)).toBe(canonicalSerialize(b));
    expect(canonicalSerialize(a)).toBe('{"a":{"10":10,"2":2},"z":[{"a":{"c":3,"d":4},"b":2}]}');
  });

  it("preserves array order and JSON null/undefined semantics", () => {
    expect(canonicalSerialize({ a: [1, 2] })).not.toBe(canonicalSerialize({ a: [2, 1] }));
    expect(canonicalSerialize({ omitted: undefined, a: [undefined, null, "x"] })).toBe('{"a":[null,null,"x"]}');
  });
});

describe("report input identity", () => {
  it("is stable across nested object insertion order", () => {
    const reordered = JSON.parse(canonicalSerialize(view)) as ProjectView;
    expect(reportInputFingerprint(input({ view: reordered }))).toBe(reportInputFingerprint(input()));
  });

  it("includes project, selected run contents, scene, catalogue and topology checks", () => {
    const baseline = reportInputFingerprint(input());
    const changed: ProjectView[] = [];
    const project = structuredClone(view);
    project.bundle.project.name += " edited";
    changed.push(project);
    const run = structuredClone(view);
    run.bundle.simulation_runs[0].summary_result!.total_energy_wh += 1;
    changed.push(run);
    const scene = structuredClone(view);
    scene.bundle.scene.pv_fields[0].tilt_deg += 1;
    changed.push(scene);
    const catalogue = structuredClone(view);
    catalogue.catalog.modules[0].pmp_w += 1;
    changed.push(catalogue);
    const topology = structuredClone(view);
    topology.topology_checks = undefined;
    // Make the difference explicit even if the fixture has no live checks.
    expect(reportInputFingerprint(input({ view: { ...topology, topology_checks: { basis: "stc_reference_conditions_only", strings: [] } } }))).not.toBe(reportInputFingerprint(input({ view: topology })));
    for (const v of changed) expect(reportInputFingerprint(input({ view: v }))).not.toBe(baseline);
  });

  it("includes run selection, authority, hourly values and their array order", () => {
    const baseline = reportInputFingerprint(input());
    for (const over of [
      { runId: "another-run" },
      { authority: "ENGINE" as const },
      { hourlyAcKw: [[1, 2]] }
    ]) expect(reportInputFingerprint(input(over))).not.toBe(baseline);
    expect(reportInputFingerprint(input({ hourlyAcKw: [[1, 2]] }))).not.toBe(reportInputFingerprint(input({ hourlyAcKw: [[2, 1]] })));
  });

  it("includes entities and modules in their supplied order", () => {
    const entities = ["a", "b"].map<Entity>((id) => ({
      id, kind: "surface", subtype: "roof", name: id,
      polygon: [[0, 0], [1, 0], [1, 1]], holes: [], plane: { mode: "flat", z_m: 0 },
      height_m: 0, source: "engine", modified: false, pending: [], locked: false, hidden: false, hostsPvField: false
    }));
    const modules = ["a", "b"].map<ModuleShape>((id) => ({
      id, fieldId: "field", polygon: [[0, 0], [1, 0], [1, 1]], stringId: null, mpptKey: null
    }));
    expect(reportInputFingerprint(input({ entities }))).not.toBe(reportInputFingerprint(input()));
    expect(reportInputFingerprint(input({ entities }))).not.toBe(reportInputFingerprint(input({ entities: [...entities].reverse() })));
    expect(reportInputFingerprint(input({ modules }))).not.toBe(reportInputFingerprint(input()));
    expect(reportInputFingerprint(input({ modules }))).not.toBe(reportInputFingerprint(input({ modules: [...modules].reverse() })));
  });

  it("includes address text and attribution but normalizes blank and trimmed addresses", () => {
    const baseline = reportInputFingerprint(input());
    expect(reportInputFingerprint(input({ address: { ...address, text: "Jalan Baru 2" } }))).not.toBe(baseline);
    expect(reportInputFingerprint(input({ address: { ...address, attribution: "© Other" } }))).not.toBe(baseline);
    expect(reportInputFingerprint(input({ address: { ...address, text: `  ${address.text}  ` } }))).toBe(baseline);
    expect(reportInputFingerprint(input({ address: { ...address, text: "  " } }))).toBe(reportInputFingerprint(input({ address: null })));
  });

  it("includes language, tier, effective branding and all system fields", () => {
    const baseline = reportInputFingerprint(input());
    for (const over of [
      { language: "id" },
      { tier: "branded" as const },
      { system: { ...EMPTY_SYSTEM, installationType: "hybrid" as const } },
      { system: { ...EMPTY_SYSTEM, bessEnergyKwh: 1000 } },
      { system: { ...EMPTY_SYSTEM, bessPowerKw: 500 } }
    ]) expect(reportInputFingerprint(input(over))).not.toBe(baseline);
    const branded = input({ tier: "branded", branding: "Customer A" });
    expect(reportInputFingerprint({ ...branded, branding: "Customer B" })).not.toBe(reportInputFingerprint(branded));
    expect(reportInputFingerprint({ ...branded, branding: "  Customer A  " })).toBe(reportInputFingerprint(branded));
  });

  it("normalizes Free branding to unbranded and absent system info to defaults", () => {
    expect(reportInputFingerprint(input({ branding: "Ignored customer" }))).toBe(reportInputFingerprint(input()));
    expect(reportInputFingerprint(input({ system: EMPTY_SYSTEM }))).toBe(reportInputFingerprint(input()));
  });

  it("excludes generation time, address lookup metadata and bundle update clock", () => {
    const otherView = structuredClone(view);
    otherView.bundle.updated_at = "2030-01-01T00:00:00Z";
    expect(reportInputFingerprint(input({
      view: otherView,
      now: new Date("2030-01-01T00:00:00Z"),
      address: { ...address, source: "user", lat: 0, lon: 0, updatedAt: "2030-01-01T00:00:00Z" }
    }))).toBe(reportInputFingerprint(input({ now: new Date("2026-10-25T00:00:00Z") })));
  });
});

describe("immutable report snapshots", () => {
  it("preserves exact HTML, model identity and generation time", () => {
    const model = buildResultModel(view, view.bundle.simulation_runs[0], { authority: "DEMO_SYNTHETIC", hourlyAcKw: null });
    const report = { html: "<!doctype html><html>exact report</html>", fingerprint: modelFingerprint(model) };
    const fp = reportInputFingerprint(input());
    const snapshot = createReportSnapshot(report, fp, "2026-10-25T00:00:00.000Z");
    expect(snapshot.html).toBe(report.html);
    expect(snapshot.modelFingerprint).toBe(modelFingerprint(model));
    expect(snapshot.inputFingerprint).toBe(fp);
    expect(snapshot.generatedAt).toBe("2026-10-25T00:00:00.000Z");
    expect(Object.isFrozen(snapshot)).toBe(true);
    expect(Reflect.set(snapshot, "html", "changed")).toBe(false);
  });

  it("repeats for identical input and HTML, and changes with exact HTML or input", () => {
    const report = { html: "<html>report</html>", fingerprint: "engineering-fingerprint" };
    const first = createReportSnapshot(report, "input-a", "2026-10-25T00:00:00Z");
    expect(createReportSnapshot(report, "input-a", "2030-01-01T00:00:00Z").snapshotId).toBe(first.snapshotId);
    expect(createReportSnapshot({ ...report, html: report.html + "\n" }, "input-a", first.generatedAt).snapshotId).not.toBe(first.snapshotId);
    expect(createReportSnapshot(report, "input-b", first.generatedAt).snapshotId).not.toBe(first.snapshotId);
  });
});
