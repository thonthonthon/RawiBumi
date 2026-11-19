import Flatbush from "flatbush";
import { pointInPolygon, type Vec2 } from "../../geometry";
import type { ModuleShape } from "../../state/store";
import type { Box } from "./viewport";

/**
 * 2D spatial index over module footprints (flatbush, ADR 0002). Picking a
 * point checks only the footprints whose boxes contain it, so it stays well
 * under a millisecond at 100k modules.
 */
export class ModuleIndex {
  private readonly index: Flatbush | null;
  readonly bounds: Box | null;

  constructor(private readonly modules: readonly ModuleShape[]) {
    if (!modules.length) {
      this.index = null;
      this.bounds = null;
      return;
    }
    const index = new Flatbush(modules.length);
    for (const m of modules) {
      let minX = Infinity;
      let minY = Infinity;
      let maxX = -Infinity;
      let maxY = -Infinity;
      for (const [x, y] of m.polygon) {
        if (x < minX) minX = x;
        if (y < minY) minY = y;
        if (x > maxX) maxX = x;
        if (y > maxY) maxY = y;
      }
      index.add(minX, minY, maxX, maxY);
    }
    index.finish();
    this.index = index;
    this.bounds = { minX: index.minX, minY: index.minY, maxX: index.maxX, maxY: index.maxY };
  }

  get size(): number {
    return this.modules.length;
  }

  /** Id of the module under the point; the last drawn wins where footprints overlap. */
  pick(p: Vec2): string | null {
    if (!this.index) return null;
    const hits = this.index.search(p[0], p[1], p[0], p[1]);
    let best = -1;
    for (const i of hits) if (i > best && pointInPolygon(p, this.modules[i].polygon)) best = i;
    return best >= 0 ? this.modules[best].id : null;
  }

  /** Indices of modules whose boxes touch the given box. */
  search(box: Box): number[] {
    return this.index ? this.index.search(box.minX, box.minY, box.maxX, box.maxY) : [];
  }
}
