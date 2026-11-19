import {
  BufferGeometry,
  Color,
  Float32BufferAttribute,
  Group,
  LineBasicMaterial,
  LineDashedMaterial,
  LineLoop,
  Mesh,
  MeshBasicMaterial,
  Path,
  Shape,
  ShapeGeometry,
  ShaderMaterial,
  DoubleSide,
  Vector2,
  type Material
} from "three";
import type { Vec2 } from "../../geometry";
import type { Entity } from "../../state/store";
import { tokenColor } from "./colors";

/** Screen-space hatch with a transparent background, for keep-out zones. */
function hatchMaterial(color: Color): ShaderMaterial {
  return new ShaderMaterial({
    transparent: true,
    depthWrite: false,
    side: DoubleSide,
    uniforms: { uColor: { value: color }, uDpr: { value: 1 } },
    vertexShader: "void main() { gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: `uniform vec3 uColor; uniform float uDpr;
void main() {
  float h = mod(gl_FragCoord.x - gl_FragCoord.y, 8.0 * uDpr);
  if (h >= 1.2 * uDpr) discard;
  gl_FragColor = vec4(uColor, 1.0);
}`
  });
}

export function shapeOf(e: Pick<Entity, "polygon" | "holes">): Shape {
  const s = new Shape(e.polygon.map(([x, y]) => new Vector2(x, y)));
  for (const h of e.holes) s.holes.push(new Path(h.map(([x, y]) => new Vector2(x, y))));
  return s;
}

export function ringGeometry(ring: Vec2[], z = 0): BufferGeometry {
  const g = new BufferGeometry();
  g.setAttribute("position", new Float32BufferAttribute(ring.flatMap(([x, y]) => [x, y, z]), 3));
  return g;
}

/** Draw order of the plan layers (painter's order; no depth test in the plan). */
export const ORDER = { surface: 0, keepout: 1, modules: 2, obstacle: 3 } as const;

interface Styles {
  surfaceFill: MeshBasicMaterial;
  draftFill: MeshBasicMaterial;
  surfaceLine: LineBasicMaterial;
  surfaceDash: LineDashedMaterial;
  draftDash: LineDashedMaterial;
  keepoutFill: ShaderMaterial;
  keepoutDash: LineDashedMaterial;
  obstacleFill: MeshBasicMaterial;
  obstacleDraftFill: MeshBasicMaterial;
  obstacleLine: LineBasicMaterial;
  obstacleDash: LineDashedMaterial;
}

/**
 * Surfaces, keep-out zones and obstacles of the plan as flat three.js shapes.
 * Line widths are 1 px (WebGL); the selected entity's 2 px outline, vertex
 * handles and labels are drawn on the 2D overlay instead.
 */
export class PlanEntities {
  readonly group = new Group();
  private readonly styles: Styles;
  private readonly dashed: LineDashedMaterial[];

  constructor() {
    const flat = (color: Color, opacity = 1) =>
      new MeshBasicMaterial({ color, transparent: opacity < 1, opacity, depthTest: false, depthWrite: false, side: DoubleSide });
    const dash = (color: Color) => new LineDashedMaterial({ color, dashSize: 6, gapSize: 4, depthTest: false });
    this.styles = {
      surfaceFill: flat(tokenColor("role-stage-surface")),
      draftFill: flat(tokenColor("role-warning-glyph"), 0.14),
      surfaceLine: new LineBasicMaterial({ color: tokenColor("role-stage-muted"), depthTest: false }),
      surfaceDash: dash(tokenColor("role-stage-muted")),
      draftDash: dash(tokenColor("role-warning-glyph")),
      keepoutFill: hatchMaterial(tokenColor("role-error-glyph")),
      keepoutDash: dash(tokenColor("role-error-glyph")),
      obstacleFill: flat(tokenColor("color-graphite-700")),
      obstacleDraftFill: flat(tokenColor("color-graphite-700"), 0.5),
      obstacleLine: new LineBasicMaterial({ color: tokenColor("color-chalk-300"), depthTest: false }),
      obstacleDash: dash(tokenColor("color-chalk-300"))
    };
    this.dashed = [this.styles.surfaceDash, this.styles.draftDash, this.styles.keepoutDash, this.styles.obstacleDash];
  }

  set(entities: readonly Entity[]): void {
    this.clear();
    const s = this.styles;
    for (const e of entities) {
      if (e.hidden) continue;
      const draft = e.source === "draft";
      const changed = draft || e.modified;
      let fill: Material;
      let line: Material;
      let order: number;
      if (e.kind === "surface") {
        fill = draft ? s.draftFill : s.surfaceFill;
        line = draft ? s.draftDash : changed ? s.surfaceDash : s.surfaceLine;
        order = ORDER.surface;
      } else if (e.kind === "keepout") {
        fill = s.keepoutFill;
        line = s.keepoutDash;
        order = ORDER.keepout;
      } else {
        fill = draft ? s.obstacleDraftFill : s.obstacleFill;
        line = changed ? s.obstacleDash : s.obstacleLine;
        order = ORDER.obstacle;
      }
      const mesh = new Mesh(new ShapeGeometry(shapeOf(e)), fill);
      mesh.renderOrder = order * 10;
      this.group.add(mesh);
      for (const ring of [e.polygon, ...e.holes]) {
        const l = new LineLoop(ringGeometry(ring), line);
        if (line instanceof LineDashedMaterial) l.computeLineDistances();
        l.renderOrder = order * 10 + 1;
        this.group.add(l);
      }
    }
  }

  /** Dashes are specified in screen pixels; convert at the current zoom. */
  setScale(pxPerMetre: number, dpr: number): void {
    for (const m of this.dashed) {
      m.dashSize = 6 / pxPerMetre;
      m.gapSize = 4 / pxPerMetre;
    }
    this.styles.keepoutFill.uniforms.uDpr.value = dpr;
  }

  private clear(): void {
    for (const c of [...this.group.children]) {
      (c as Mesh).geometry?.dispose();
      this.group.remove(c);
    }
  }

  dispose(): void {
    this.clear();
    for (const m of Object.values(this.styles)) (m as Material).dispose();
  }
}
