import { OrthographicCamera, PerspectiveCamera, Vector3 } from "three";
import { bounds, planeZ } from "../geometry";
import type { Entity } from "../state/store";

export const VIEW_PRESETS = [
  { id: "plan", label: "top", keys: "Shift+t" },
  { id: "front", label: "front", keys: "Shift+f" },
  { id: "back", label: "back" },
  { id: "left", label: "left" },
  { id: "right", label: "right" },
  { id: "isometric", label: "isometric", keys: "Shift+i" },
  { id: "face", label: "face" }
] as const;
export type GeometryView = typeof VIEW_PRESETS[number]["id"];
export type CameraFrame = { centre: [number, number, number]; span: number };

export function selectedRoof(entities: Entity[], selection: string[]): Entity | undefined {
  return entities.find(e => selection.includes(e.id) && e.kind === "surface" && ["flat_roof", "pitched_roof"].includes(e.subtype) && !e.hidden);
}

/** All directions use the scene's X east, Y north, Z up coordinates. */
export function presetCamera(preset: GeometryView, frame: CameraFrame, aspect: number, roof?: Entity) {
  let centre = new Vector3(...frame.centre);
  let span = Math.max(frame.span, 1);
  const el = 35 * Math.PI / 180;
  let outward = new Vector3(-0.6 * Math.cos(el), -0.8 * Math.cos(el), Math.sin(el));
  if (preset === "plan") outward.set(0, 0, 1);
  if (preset === "front") outward.set(0, -1, 0);
  if (preset === "back") outward.set(0, 1, 0);
  if (preset === "left") outward.set(-1, 0, 0);
  if (preset === "right") outward.set(1, 0, 0);
  if (preset === "face" && roof) {
    const box = bounds([roof.polygon]);
    const x = (box.minX + box.maxX) / 2, y = (box.minY + box.maxY) / 2;
    const z = planeZ(roof.polygon, roof.plane, [x, y])!;
    // Sample the canonical UI plane so edge tilt and datum/azimuth share the same normal.
    outward.set(z - planeZ(roof.polygon, roof.plane, [x + 1, y])!, z - planeZ(roof.polygon, roof.plane, [x, y + 1])!, 1).normalize();
    centre = new Vector3(x, y, z);
    span = Math.max(1, ...roof.polygon.map(([px, py]) => 2 * new Vector3(px, py, planeZ(roof.polygon, roof.plane, [px, py])!).distanceTo(centre))) * 1.15;
  }
  const d = span * 1.25;
  const halfH = span / 2 / Math.min(aspect, 1);
  const camera = preset === "isometric"
    ? new PerspectiveCamera(40, aspect, 0.1, Math.max(20000, d * 20))
    : new OrthographicCamera(-halfH * aspect, halfH * aspect, halfH, -halfH, 0.1, Math.max(20000, d * 20));
  camera.up.set(0, 0, 1);
  if (Math.abs(outward.z) > 0.999) camera.up.set(0, 1, 0);
  camera.position.copy(centre).addScaledVector(outward, d);
  camera.lookAt(centre);
  camera.updateProjectionMatrix();
  return { camera, target: centre };
}
