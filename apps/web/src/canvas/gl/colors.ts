import { Color, ColorManagement } from "three";
import { rgbOf } from "../../ui/palette";

// Token colours are sRGB hex values drawn as-is, the same as on the 2D canvas
// and in CSS. Turning colour management off keeps three.js from converting
// them to linear and back.
ColorManagement.enabled = false;

/** A token colour as a three.js Color. */
export function tokenColor(name: string): Color {
  const [r, g, b] = rgbOf(name);
  return new Color(r / 255, g / 255, b / 255);
}

/** Module look in the plan and 3D views. */
export interface ModuleLook {
  color: Color;
  /** 1 = hatched (unassigned in the electrical step), 0 = solid. */
  hatch: number;
  alpha: number;
  /** Drawn with a 2 px selection outline; the fill keeps its colour (DESIGN.md §6). */
  selected: boolean;
}

export interface ModuleLookInput {
  mpptKey: string | null;
  stringId: string | null;
}

/**
 * Shared by the plan and 3D views so both colour modules the same way.
 * Electrical step: MPPT hue at 0.75 opacity with a 1 px outline in the same
 * hue; unassigned modules hatched (DESIGN.md §6).
 */
export function moduleLooks(electrical: boolean) {
  const mppt = Array.from({ length: 8 }, (_, i) => tokenColor(`color-mppt-screen-${i + 1}`));
  const module = tokenColor("role-stage-module");
  const muted = tokenColor("role-stage-muted");
  return (m: ModuleLookInput, selected: boolean): ModuleLook => {
    if (!electrical) return { color: module, hatch: 0, alpha: 0.55, selected };
    if (m.mpptKey) return { color: mppt[(Number(m.mpptKey.split("#")[1]) || 0) % 8], hatch: 0, alpha: 0.75, selected };
    if (m.stringId) return { color: muted, hatch: 0, alpha: 0.45, selected };
    return { color: muted, hatch: 1, alpha: 1, selected };
  };
}
