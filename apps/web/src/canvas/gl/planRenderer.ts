import { LinearSRGBColorSpace, OrthographicCamera, Scene, WebGLRenderer } from "three";
import type { Entity, ModuleShape } from "../../state/store";
import type { Size, ViewT } from "../plan/viewport";
import { moduleLooks, tokenColor } from "./colors";
import { ORDER, PlanEntities } from "./entities";
import { ModuleMesh, moduleMaterial } from "./modules";

/** Frame timing for the `?perf` overlay and the performance test. */
export interface FrameStats {
  /** JavaScript time of the last WebGL frame, ms (GPU time is not included). */
  lastFrameMs: number;
  frames: number;
}

/**
 * The WebGL layer of the plan: surfaces, keep-outs, modules and obstacles.
 * The camera is orthographic, looking down, with the same centre and zoom as
 * the 2D layers, so the three canvases line up pixel for pixel (ADR 0002, 0009).
 * Frames are drawn on demand, at most once per animation frame.
 */
export class PlanRenderer {
  readonly stats: FrameStats = { lastFrameMs: 0, frames: 0 };
  private readonly renderer: WebGLRenderer;
  private readonly scene = new Scene();
  private readonly camera = new OrthographicCamera(-1, 1, 1, -1, -1000, 1000);
  private readonly entities = new PlanEntities();
  private readonly material = moduleMaterial();
  private modules: ModuleMesh | null = null;
  private moduleList: readonly ModuleShape[] = [];
  private pending = 0;
  private size: Size = { w: 1, h: 1 };
  private dpr = 1;

  constructor(canvas: HTMLCanvasElement) {
    this.renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
    this.renderer.setClearColor(0x000000, 0);
    // Token colours are already sRGB; write them unchanged (see colors.ts).
    this.renderer.outputColorSpace = LinearSRGBColorSpace;
    this.camera.position.set(0, 0, 100);
    this.scene.add(this.entities.group);
    this.material.uniforms.uEdgeColor.value = tokenColor("role-stage-module");
    this.material.uniforms.uSelColor.value = tokenColor("role-selection");
    this.material.uniforms.uHatchColor.value = tokenColor("role-stage-muted");
    this.material.uniforms.uHatchBg.value = tokenColor("role-stage-surface");
  }

  setSize(size: Size, dpr: number): void {
    this.size = size;
    this.dpr = dpr;
    this.renderer.setPixelRatio(dpr);
    this.renderer.setSize(size.w, size.h, false);
    this.material.uniforms.uDpr.value = dpr;
  }

  setView(view: ViewT): void {
    const hw = this.size.w / 2 / view.scale;
    const hh = this.size.h / 2 / view.scale;
    this.camera.left = -hw;
    this.camera.right = hw;
    this.camera.top = hh;
    this.camera.bottom = -hh;
    this.camera.position.set(view.cx, view.cy, 100);
    this.camera.updateProjectionMatrix();
    this.entities.setScale(view.scale, this.dpr);
    // Module edges only when a module is wide enough on screen to show them.
    this.material.uniforms.uEdge.value = view.scale > 7 ? 1 : 0;
  }

  setEntities(entities: readonly Entity[]): void {
    this.entities.set(entities);
  }

  setModules(modules: readonly ModuleShape[]): void {
    if (modules === this.moduleList) return;
    if (this.modules) {
      this.scene.remove(this.modules.group);
      this.modules.dispose();
    }
    this.moduleList = modules;
    this.modules = modules.length ? new ModuleMesh(modules, this.material) : null;
    if (this.modules) {
      this.modules.renderOrder = ORDER.modules * 10;
      this.scene.add(this.modules.group);
    }
  }

  private looksFor: { modules: readonly ModuleShape[]; electrical: boolean; selected: ReadonlySet<string> } | null = null;

  /**
   * Module colours: by MPPT in the electrical step, with a selection outline.
   * A selection change on the same layout and step rewrites only the modules
   * whose selection changed (a full rewrite takes about 100 ms at 100k).
   */
  setModuleLooks(electrical: boolean, selected: ReadonlySet<string>): void {
    if (!this.modules) return;
    const look = moduleLooks(electrical);
    const prev = this.looksFor;
    this.looksFor = { modules: this.moduleList, electrical, selected };
    if (prev && prev.modules === this.moduleList && prev.electrical === electrical) {
      for (const id of new Set([...prev.selected, ...selected])) {
        if (prev.selected.has(id) === selected.has(id)) continue;
        const i = this.modules.indexOf(id);
        if (i !== undefined) this.modules.setLook(i, look(this.moduleList[i], selected.has(id)));
      }
      return;
    }
    this.material.uniforms.uEdgeColor.value = tokenColor("role-stage-module");
    this.material.uniforms.uEdgeOwnHue.value = electrical ? 1 : 0;
    this.modules.setLooks((m) => look(m, selected.has(m.id)));
  }

  /** Ask for a frame; several requests in one animation frame draw once. */
  invalidate(): void {
    if (this.pending) return;
    this.pending = requestAnimationFrame(() => {
      this.pending = 0;
      this.renderNow();
    });
  }

  renderNow(): void {
    const t0 = performance.now();
    this.renderer.render(this.scene, this.camera);
    this.stats.lastFrameMs = performance.now() - t0;
    this.stats.frames++;
  }

  dispose(): void {
    cancelAnimationFrame(this.pending);
    this.modules?.dispose();
    this.entities.dispose();
    this.material.dispose();
    this.renderer.dispose();
  }
}

/** True when this browser can create a WebGL2 context. */
export function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl2");
    const available = !!gl;
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
    return available;
  } catch {
    return false;
  }
}
