import { BufferAttribute, BufferGeometry, Color, DoubleSide, DynamicDrawUsage, Group, Mesh, ShaderMaterial } from "three";
import type { Vec2 } from "../../geometry";
import type { ModuleShape } from "../../state/store";
import type { ModuleLook } from "./colors";

/**
 * Modules as merged quads in chunks of CHUNK modules. Each chunk is one draw
 * call with its own bounds, so zoomed-in views skip chunks off screen.
 *
 * Why not one InstancedMesh (ADR 0002)? On software WebGL (SwiftShader, which
 * Chrome falls back to on blocklisted drivers, virtual machines and some
 * remote desktops) 100k instances took 2.7 s per frame against 0.46 s merged.
 * On hardware GPUs both are fast. See ADR 0009.
 *
 * The shader draws the 0.8 px module edge and the screen-space hatch for
 * unassigned modules, so neither needs extra geometry.
 */
export const CHUNK = 8192;

const VERTEX = /* glsl */ `
attribute vec3 aColor;
attribute vec3 aLook; // x: hatch, y: fill alpha, z: selected
varying vec2 vUv;
varying vec3 vColor;
varying vec3 vLook;
void main() {
  vUv = uv;
  vColor = aColor;
  vLook = aLook;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

const FRAGMENT = /* glsl */ `
uniform float uEdge;
uniform float uEdgeOwnHue;
uniform vec3 uEdgeColor;
uniform vec3 uSelColor;
uniform vec3 uHatchColor;
uniform vec3 uHatchBg;
uniform float uDpr;
varying vec2 vUv;
varying vec3 vColor;
varying vec3 vLook;
void main() {
  vec3 col = vColor;
  float a = vLook.y;
  if (vLook.x > 0.5) {
    float h = mod(gl_FragCoord.x - gl_FragCoord.y, 8.0 * uDpr);
    col = h < 1.2 * uDpr ? uHatchColor : uHatchBg;
    a = 1.0;
  }
  vec2 fw = fwidth(vUv);
  vec2 d = min(vUv, 1.0 - vUv) / max(fw, vec2(1e-6)); // distance to the module edge, device px
  float edge = min(d.x, d.y);
  float wide = max(fw.x, fw.y) < 0.15 / uDpr ? 1.0 : 0.0; // module at least about 7 px across
  // 1 px outline (DESIGN.md §6): the module's own hue, or a uniform colour.
  if (uEdge > 0.5 && wide > 0.5 && edge < 1.0 * uDpr) { col = uEdgeOwnHue > 0.5 ? vColor : uEdgeColor; a = 1.0; }
  // Selection: a 2 px outline, fill unchanged; modules too small for an outline turn the selection colour.
  if (vLook.z > 0.5 && (wide < 0.5 || edge < 2.0 * uDpr)) { col = uSelColor; a = 1.0; }
  gl_FragColor = vec4(col, a);
}`;

export function moduleMaterial(): ShaderMaterial {
  return new ShaderMaterial({
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
    transparent: true,
    depthWrite: false,
    side: DoubleSide,
    uniforms: {
      uEdge: { value: 0 },
      uEdgeOwnHue: { value: 0 },
      uEdgeColor: { value: new Color() },
      uSelColor: { value: new Color() },
      uHatchColor: { value: new Color() },
      uHatchBg: { value: new Color() },
      uDpr: { value: 1 }
    }
  });
}

/** The four corners of a footprint; footprints that are not four-cornered use their bounding box. */
export function corners(poly: Vec2[]): [Vec2, Vec2, Vec2, Vec2] {
  if (poly.length === 4) return [poly[0], poly[1], poly[2], poly[3]];
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of poly) {
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }
  return [
    [minX, minY],
    [maxX, minY],
    [maxX, maxY],
    [minX, maxY]
  ];
}

const UV = [0, 0, 1, 0, 1, 1, 0, 1];

export class ModuleMesh {
  readonly group = new Group();
  private readonly chunks: Array<{ mesh: Mesh; start: number; count: number }> = [];
  private readonly ids: Map<string, number>;

  constructor(
    private readonly modules: readonly ModuleShape[],
    material: ShaderMaterial,
    /** Height of each footprint corner (the 3D preview tilts modules this way); 0 in the plan. */
    zOf: (m: ModuleShape, corners: readonly Vec2[]) => readonly number[] = () => [0, 0, 0, 0]
  ) {
    this.ids = new Map(modules.map((m, i) => [m.id, i]));
    for (let start = 0; start < modules.length; start += CHUNK) {
      const count = Math.min(CHUNK, modules.length - start);
      const pos = new Float32Array(count * 12);
      const uv = new Float32Array(count * 8);
      const index = new Uint32Array(count * 6);
      for (let k = 0; k < count; k++) {
        const m = modules[start + k];
        const c = corners(m.polygon);
        const z = zOf(m, c);
        for (let j = 0; j < 4; j++) {
          pos[k * 12 + j * 3] = c[j][0];
          pos[k * 12 + j * 3 + 1] = c[j][1];
          pos[k * 12 + j * 3 + 2] = z[j];
        }
        uv.set(UV, k * 8);
        const v = k * 4;
        index.set([v, v + 1, v + 2, v, v + 2, v + 3], k * 6);
      }
      const g = new BufferGeometry();
      g.setAttribute("position", new BufferAttribute(pos, 3));
      g.setAttribute("uv", new BufferAttribute(uv, 2));
      g.setAttribute("aColor", new BufferAttribute(new Float32Array(count * 12), 3).setUsage(DynamicDrawUsage));
      g.setAttribute("aLook", new BufferAttribute(new Float32Array(count * 12), 3).setUsage(DynamicDrawUsage));
      g.setIndex(new BufferAttribute(index, 1));
      g.computeBoundingSphere();
      g.computeBoundingBox();
      const mesh = new Mesh(g, material);
      this.chunks.push({ mesh, start, count });
      this.group.add(mesh);
    }
  }

  set renderOrder(order: number) {
    for (const c of this.chunks) c.mesh.renderOrder = order;
  }

  /** Colour, hatch and opacity of every module. */
  setLooks(lookOf: (m: ModuleShape, i: number) => ModuleLook): void {
    for (const { mesh, start, count } of this.chunks) {
      const col = mesh.geometry.getAttribute("aColor") as BufferAttribute;
      const look = mesh.geometry.getAttribute("aLook") as BufferAttribute;
      const ca = col.array as Float32Array;
      const la = look.array as Float32Array;
      for (let k = 0; k < count; k++) {
        const l = lookOf(this.modules[start + k], start + k);
        for (let j = 0; j < 4; j++) {
          ca[k * 12 + j * 3] = l.color.r;
          ca[k * 12 + j * 3 + 1] = l.color.g;
          ca[k * 12 + j * 3 + 2] = l.color.b;
          la[k * 12 + j * 3] = l.hatch;
          la[k * 12 + j * 3 + 1] = l.alpha;
          la[k * 12 + j * 3 + 2] = l.selected ? 1 : 0;
        }
      }
      col.clearUpdateRanges();
      look.clearUpdateRanges();
      col.needsUpdate = true;
      look.needsUpdate = true;
    }
  }

  /** Index of a module id, or undefined when it is not in this layout. */
  indexOf(id: string): number | undefined {
    return this.ids.get(id);
  }

  /** Update one module's look; uploads only that module's vertices. */
  setLook(i: number, l: ModuleLook): void {
    const chunk = this.chunks[Math.floor(i / CHUNK)];
    if (!chunk) return;
    const k = i - chunk.start;
    const col = chunk.mesh.geometry.getAttribute("aColor") as BufferAttribute;
    const look = chunk.mesh.geometry.getAttribute("aLook") as BufferAttribute;
    const ca = col.array as Float32Array;
    const la = look.array as Float32Array;
    for (let j = 0; j < 4; j++) {
      ca.set([l.color.r, l.color.g, l.color.b], k * 12 + j * 3);
      la.set([l.hatch, l.alpha, l.selected ? 1 : 0], k * 12 + j * 3);
    }
    col.addUpdateRange(k * 12, 12);
    look.addUpdateRange(k * 12, 12);
    col.needsUpdate = true;
    look.needsUpdate = true;
  }

  dispose(): void {
    for (const c of this.chunks) c.mesh.geometry.dispose();
  }
}
