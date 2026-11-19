import { describe, expect, it } from "vitest";
import type { Vec2 } from "../../src/geometry";
import { moduleHeights, PREVIEW_MODULE_OFFSET_M } from "../../src/canvas/gl/scene3d";
import type { Entity, ModuleShape } from "../../src/state/store";

const roof: Entity = {
  id: "roof",
  kind: "surface",
  subtype: "flat_roof",
  name: "Concrete roof",
  polygon: [[0, 0], [20, 0], [20, 10], [0, 10]],
  holes: [],
  plane: { mode: "flat", z_m: 6 },
  height_m: 0,
  source: "engine",
  modified: false,
  pending: [],
  locked: false,
  hidden: false,
  hostsPvField: true
};

// A portrait module 1.134 × 2.278 m at 10° tilt: footprint depth 2.278 × cos 10°.
const depth = 2.278 * Math.cos((10 * Math.PI) / 180);
const footprint: Vec2[] = [[1, 1], [2.134, 1], [2.134, 1 + depth], [1, 1 + depth]];
const module: ModuleShape = { id: "m1", fieldId: "f1", polygon: footprint, stringId: null, mpptKey: null };

describe("3D preview module heights (flat concrete roof, manual rack tilt)", () => {
  it("lifts the back edge by module length × sin(tilt), facing the azimuth", () => {
    const north = moduleHeights([roof], new Map([["f1", { supportSurfaceId: "roof", tiltDeg: 10, azimuthDeg: 0 }]]))(module, footprint);
    const base = 6 + PREVIEW_MODULE_OFFSET_M;
    // Facing north (+Y): the north edge (corners 2, 3) is low, the south edge rises.
    expect(north[2]).toBeCloseTo(base, 9);
    expect(north[3]).toBeCloseTo(base, 9);
    expect(north[0]).toBeCloseTo(base + 2.278 * Math.sin((10 * Math.PI) / 180), 9);
    expect(north[1]).toBeCloseTo(north[0], 9);
    const south = moduleHeights([roof], new Map([["f1", { supportSurfaceId: "roof", tiltDeg: 10, azimuthDeg: 180 }]]))(module, footprint);
    expect(south[0]).toBeCloseTo(base, 9);
    expect(south[2]).toBeCloseTo(north[0], 9);
  });

  it("keeps 0° tilt flat and falls back to the ground without a field", () => {
    const flat = moduleHeights([roof], new Map([["f1", { supportSurfaceId: "roof", tiltDeg: 0, azimuthDeg: 0 }]]))(module, footprint);
    expect(new Set(flat).size).toBe(1);
    const orphan = moduleHeights([roof], new Map())(module, footprint);
    expect(orphan).toEqual([PREVIEW_MODULE_OFFSET_M, PREVIEW_MODULE_OFFSET_M, PREVIEW_MODULE_OFFSET_M, PREVIEW_MODULE_OFFSET_M]);
  });

  it("uses the field's mounting height when it has one", () => {
    const h = moduleHeights([roof], new Map([["f1", { supportSurfaceId: "roof", tiltDeg: 0, azimuthDeg: 0, mountingHeightM: 0.6 }]]))(module, footprint);
    expect(h).toEqual([6.6, 6.6, 6.6, 6.6].map((x) => expect.closeTo(x, 9)));
  });
});
