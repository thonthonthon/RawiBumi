import { beforeEach, describe, expect, it } from "vitest";
import { legacyFieldInput } from "../../src/engine/layout";
import { mockApi } from "../../src/demo/mockApi";
import { resetStore, uiStore, type Entity } from "../../src/state/store";
import { goldenRequest } from "./golden";

const draft = (id: string): Entity => ({
  id,
  kind: "surface",
  subtype: "flat_roof",
  name: id,
  polygon: [
    [0, 0],
    [1, 0],
    [1, 1]
  ],
  holes: [],
  plane: { mode: "flat", z_m: 0 },
  height_m: 0,
  source: "draft",
  modified: false,
  pending: [],
  locked: false,
  hidden: false,
  hostsPvField: false
});

describe("one history for local drafts and engine commands", () => {
  beforeEach(() => resetStore());

  it("records engine commands in order with local steps, and the reducer leaves engine steps to the engine", async () => {
    const { dispatch } = uiStore.getState();
    const view = await mockApi.project("demo-project");
    dispatch({ type: "setView", view });
    dispatch({ type: "addEntity", entity: draft("d1") });
    dispatch({ type: "engineCommitted", view, label: "Filling" });
    let s = uiStore.getState().state;
    expect(s.past.map((h) => h.kind)).toEqual(["local", "engine"]);
    // A plain undo cannot revert an engine step: nothing changes.
    dispatch({ type: "undo" });
    expect(uiStore.getState().state.past).toHaveLength(2);
    dispatch({ type: "engineUndone", view });
    s = uiStore.getState().state;
    expect(s.past.map((h) => h.kind)).toEqual(["local"]);
    expect(s.future.map((h) => h.kind)).toEqual(["engine"]);
    dispatch({ type: "undo" });
    s = uiStore.getState().state;
    expect(s.entities.some((e) => e.id === "d1")).toBe(false);
    expect(s.future.map((h) => h.kind)).toEqual(["local", "engine"]);
    dispatch({ type: "redo" });
    dispatch({ type: "engineRedone", view });
    expect(uiStore.getState().state.past.map((h) => h.kind)).toEqual(["local", "engine"]);
  });
});

describe("the demo engine session: one fill is one undo step", () => {
  it("undo after a fill restores the scene before it; redo restores the fill", async () => {
    const before = await mockApi.project("demo-project");
    const roof = await mockApi.addSurface("demo-project", { name: "Golden", origin_x_m: 100, origin_y_m: 0, width_m: 12, height_m: 8, base_elevation_m: 0, surface_type: "flat_roof" });
    const surfaceId = roof.bundle.scene.surfaces[roof.bundle.scene.surfaces.length - 1].surface_id;
    const filled = await mockApi.applyFill("demo-project", goldenRequest({ support_surface_id: surfaceId, module_definition_revision_id: "mod-demo-golden" }), null);
    expect(filled.bundle.scene.module_instances.length - roof.bundle.scene.module_instances.length).toBe(30);
    const undone = await mockApi.undo("demo-project");
    expect(undone.bundle.scene.module_instances.length).toBe(roof.bundle.scene.module_instances.length);
    expect(undone.bundle.scene.surfaces.length).toBe(before.bundle.scene.surfaces.length + 1);
    const redone = await mockApi.redo("demo-project");
    expect(redone.bundle.scene.module_instances.length).toBe(filled.bundle.scene.module_instances.length);
  });
});

describe("mapping a fill onto the engine's current PV field route", () => {
  const mod = { width_m: 1.134, height_m: 2.278 };

  it("maps one row per table with a fixed aisle to the route's row pitch", () => {
    const r = legacyFieldInput(goldenRequest({ rows_per_table: 1, tilt_deg: 10, pitch: { mode: "fixed_aisle", aisle_m: 0.6 } }), mod);
    expect(r.reasons).toEqual([]);
    expect(r.input!.row_pitch_m).toBeCloseTo(2.278 * Math.cos((10 * Math.PI) / 180) + 0.6, 12);
    expect(r.input!.perimeter_setback_m).toBe(0.4);
  });

  it("maps a GCR to slant ÷ GCR", () => {
    const r = legacyFieldInput(goldenRequest({ rows_per_table: 1, pitch: { mode: "gcr", gcr: 0.5 } }), mod);
    expect(r.input!.row_pitch_m).toBeCloseTo(2.278 / 0.5, 12);
  });

  it("lists what the route cannot do", () => {
    const r = legacyFieldInput(
      goldenRequest({ rows_per_table: 2, edge_setbacks_m: [0.4, 1, 0.4, 0.4], walkway: { every_modules: 5, width_m: 1 }, max_table_columns: 4, pitch: { mode: "shading_free", sun_elevation_deg: 30, sun_azimuth_offset_deg: 0 } }),
      mod
    );
    expect(r.input).toBeNull();
    expect(r.reasons).toHaveLength(4);
  });
});
