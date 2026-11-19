import {
  BufferGeometry,
  DoubleSide,
  Float32BufferAttribute,
  Group,
  LineBasicMaterial,
  LineLoop,
  Mesh,
  MeshLambertMaterial,
  ShapeGeometry
} from "three";
import { centroid, planeZ, type Vec2 } from "../../geometry";
import type { Entity, ModuleShape } from "../../state/store";
import { tokenColor } from "./colors";
import { ringGeometry, shapeOf } from "./entities";

/** Mounting offset of the preview modules above their roof, m (the engine's default mounting height). */
export const PREVIEW_MODULE_OFFSET_M = 0.2;

const zAt = (e: Entity, p: Vec2) => planeZ(e.polygon, e.plane, p) ?? 0;

/** A flat or tilted polygon face: triangulated in plan, each vertex lifted to its plane height. */
function face(e: Entity, lift = 0): BufferGeometry {
  const g = new ShapeGeometry(shapeOf(e));
  const pos = g.getAttribute("position");
  for (let i = 0; i < pos.count; i++) pos.setZ(i, zAt(e, [pos.getX(i), pos.getY(i)]) + lift);
  g.computeVertexNormals();
  return g;
}

/** Vertical walls along each ring, from `bottom(p)` to `top(p)`. */
function walls(rings: Vec2[][], bottom: (p: Vec2) => number, top: (p: Vec2) => number): BufferGeometry {
  const v: number[] = [];
  for (const ring of rings)
    for (let i = 0; i < ring.length; i++) {
      const a = ring[i];
      const b = ring[(i + 1) % ring.length];
      const [a0, a1, b0, b1] = [bottom(a), top(a), bottom(b), top(b)];
      v.push(a[0], a[1], a0, b[0], b[1], b0, b[0], b[1], b1, a[0], a[1], a0, b[0], b[1], b1, a[0], a[1], a1);
    }
  const g = new BufferGeometry();
  g.setAttribute("position", new Float32BufferAttribute(v, 3));
  g.computeVertexNormals();
  return g;
}

/**
 * Massing for the 3D preview: roofs as faces on their planes with walls down
 * to the ground, obstacles extruded by their height, keep-out zones as
 * outlines. Read-only; it shows the scene as the UI holds it.
 */
export function buildMassing(entities: readonly Entity[]): Group {
  const group = new Group();
  const roof = new MeshLambertMaterial({ color: tokenColor("color-graphite-700"), side: DoubleSide });
  const wall = new MeshLambertMaterial({ color: tokenColor("color-graphite-800"), side: DoubleSide });
  const obstacle = new MeshLambertMaterial({ color: tokenColor("color-chalk-300"), side: DoubleSide });
  const edge = new LineBasicMaterial({ color: tokenColor("role-stage-muted") });
  const keepout = new LineBasicMaterial({ color: tokenColor("role-error-glyph") });
  for (const e of entities) {
    if (e.hidden) continue;
    const rings = [e.polygon, ...e.holes];
    if (e.kind === "surface") {
      group.add(new Mesh(face(e), roof));
      group.add(new Mesh(walls(rings, () => 0, (p) => zAt(e, p)), wall));
      for (const r of rings) {
        group.add(new LineLoop(ringGeometry(r, 0), edge)); // footprint on the ground
        const g = ringGeometry(r);
        const pos = g.getAttribute("position");
        for (let i = 0; i < pos.count; i++) pos.setZ(i, zAt(e, [pos.getX(i), pos.getY(i)]) + 0.01);
        group.add(new LineLoop(g, edge));
      }
    } else if (e.kind === "obstacle") {
      const top = (p: Vec2) => zAt(e, p) + e.height_m;
      group.add(new Mesh(walls(rings, (p) => zAt(e, p), top), obstacle));
      group.add(new Mesh(face(e, e.height_m), obstacle));
    } else {
      for (const r of rings) {
        const g = ringGeometry(r);
        const pos = g.getAttribute("position");
        for (let i = 0; i < pos.count; i++) pos.setZ(i, zAt(e, [pos.getX(i), pos.getY(i)]) + 0.03);
        group.add(new LineLoop(g, keepout));
      }
    }
  }
  return group;
}

/** Tilt and azimuth of a PV field, as the engine stores them. */
export interface FieldMount {
  supportSurfaceId: string;
  tiltDeg: number;
  azimuthDeg: number;
  /** Height of the module's low edge above its surface, m; PREVIEW_MODULE_OFFSET_M when the field has none. */
  mountingHeightM?: number;
}

/**
 * Corner heights of each module in the preview. The module rests on its support
 * surface's plane plus a fixed mounting offset, and is tilted by its field's tilt
 * toward its azimuth, as the engine's module_axes do (geometry/scene3d/height.py):
 * the edge facing the azimuth is the low edge, and the back edge rises by
 * (footprint depth) × tan(tilt), which is module length × sin(tilt).
 * A display preview; the engine's 3D scene replaces it in Phase 7.
 */
export function moduleHeights(entities: readonly Entity[], fields: ReadonlyMap<string, FieldMount>) {
  const byId = new Map(entities.map((e) => [e.id, e]));
  return (m: ModuleShape, corners: readonly Vec2[]): number[] => {
    const f = fields.get(m.fieldId);
    const s = f ? byId.get(f.supportSurfaceId) : undefined;
    const base = (s ? zAt(s, centroid(m.polygon)) : 0) + (f?.mountingHeightM ?? PREVIEW_MODULE_OFFSET_M);
    if (!f || !(f.tiltDeg > 0) || f.tiltDeg >= 90) return corners.map(() => base);
    const az = (f.azimuthDeg * Math.PI) / 180;
    const down: Vec2 = [Math.sin(az), Math.cos(az)];
    const proj = corners.map((c) => c[0] * down[0] + c[1] * down[1]);
    const front = Math.max(...proj);
    const tan = Math.tan((f.tiltDeg * Math.PI) / 180);
    return proj.map((p) => base + (front - p) * tan);
  };
}

export function disposeGroup(group: Group): void {
  group.traverse((o) => {
    const m = o as Mesh;
    m.geometry?.dispose();
    const mat = m.material;
    if (Array.isArray(mat)) mat.forEach((x) => x.dispose());
    else mat?.dispose();
  });
}


/** Engine geometry only: indexed triangles and original face rings, with no repair. */
export function buildExactGeometry(data: import("../../types").ExactSceneGeometry, explicitFields: ReadonlySet<string>): Group {
  const group = new Group();
  const surface = new MeshLambertMaterial({color: tokenColor("color-chalk-300"), side: DoubleSide});
  const module = new MeshLambertMaterial({color: tokenColor("role-stage-module"), side: DoubleSide});
  const edge = new LineBasicMaterial({color: tokenColor("role-stage-muted")});
  const geometry = (points: readonly number[][], indices?: number[]) => {
    const g = new BufferGeometry();
    g.setAttribute("position", new Float32BufferAttribute(points.flat(), 3));
    if (indices) g.setIndex(indices);
    g.computeVertexNormals();
    return g;
  };
  for (const obstacle of data.obstacles) {
    if (obstacle.obstacle_type !== "imported_mesh" || !obstacle.visible || !obstacle.mesh) continue;
    const mesh = obstacle.mesh;
    const face = new Mesh(geometry(mesh.vertices_3d, mesh.triangles.flat()), surface);
    face.name = obstacle.obstacle_id;
    group.add(face);
    for (const ring of mesh.faces) group.add(new LineLoop(geometry(ring.vertex_indices.map(i => mesh.vertices_3d[i])), edge));
  }
  for (const item of data.modules) {
    if (!explicitFields.has(item.pv_field_id)) continue;
    if (item.status !== "resolved" || item.corners_3d.length !== 4) {
      disposeGroup(group);
      throw new Error(`${item.module_instance_id}: ${item.unresolved_reason ?? "unresolved module corners"}`);
    }
    const face = new Mesh(geometry(item.corners_3d, [0,1,2,0,2,3]), module);
    face.name = item.module_instance_id;
    group.add(face, new LineLoop(geometry(item.corners_3d), edge));
  }
  return group;
}
