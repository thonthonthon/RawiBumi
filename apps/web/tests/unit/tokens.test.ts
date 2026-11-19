import { describe, expect, it } from "vitest";
import tokens from "../../src/ui/tokens.json";

type Node = Record<string, unknown>;
const get = (p: string): string => {
  const v = p.split(".").reduce<unknown>((n, k) => (n as Node)[k], tokens) as Node;
  const raw = v.$value as string;
  const alias = raw.match(/^\{(.+)\}$/);
  return alias ? get(alias[1]) : raw;
};

function luminance(hex: string): number {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const [r, g, b] = c.map((x) => (x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};
function hue(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  if (d === 0) return 0;
  const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return (h * 60 + 360) % 360;
}

describe("design tokens", () => {
  it("keeps the selection colour from the logo palette", () => {
    expect(get("role.selection")).toBe("#FFB238");
  });

  it.each([
    ["role.panel-text", "role.panel-bg", 7],
    ["role.panel-muted", "role.panel-bg", 4.5],
    ["role.panel-muted", "role.panel-raised", 4.5],
    ["role.stage-text", "role.stage-bg", 7],
    ["role.stage-muted", "role.stage-bg", 4.5],
    ["role.stage-text", "role.stage-surface", 7],
    ["role.selection-text", "role.panel-bg", 4.5],
    ["role.warning-text", "role.panel-bg", 4.5],
    ["role.error-text", "role.panel-bg", 4.5],
    ["role.error-text", "role.shell-bg", 4.5],
    ["role.valid", "role.panel-bg", 4.5],
    ["role.link", "role.panel-bg", 4.5],
    ["role.info-on-stage", "role.stage-bg", 4.5],
    ["role.panel-text", "role.shell-bg", 7],
    ["role.panel-muted", "role.shell-bg", 4.5],
    ["role.primary-text", "role.primary-bg", 7],
    ["role.stage-muted", "role.stage-toolbar", 4.5],
    ["role.chart-1", "role.panel-raised", 4.5],
    ["role.chart-loss", "role.panel-raised", 4.5],
    ["color.paper.ink", "color.paper.white", 7],
    ["color.paper.muted", "color.paper.white", 4.5]
  ])("text %s on %s meets %s:1", (fg, bg, min) => {
    expect(contrast(get(fg), get(bg))).toBeGreaterThanOrEqual(min);
  });

  it.each([
    ["role.selection", "role.stage-bg"],
    ["role.warning-glyph", "role.stage-bg"],
    ["role.error-glyph", "role.stage-bg"],
    ["role.control-border", "role.panel-bg"],
    ["role.control-border", "role.panel-raised"],
    ["role.control-border", "role.shell-bg"],
    ["role.focus", "role.shell-bg"],
    ["role.focus", "role.panel-bg"]
  ])("glyph or boundary %s on %s meets 3:1 (WCAG 1.4.11)", (fg, bg) => {
    expect(contrast(get(fg), get(bg))).toBeGreaterThanOrEqual(3);
  });

  it("MPPT colours avoid the red-to-yellow range used for selection and status", () => {
    for (const i of ["1", "2", "3", "4", "5", "6", "7", "8"]) {
      const h = hue(get(`color.mppt.screen.${i}`));
      expect(h >= 345 || h <= 60, `mppt.screen.${i} hue ${h.toFixed(0)}`).toBe(false);
    }
  });

  it("uses only the allowed spacing steps and radii", () => {
    const space = Object.entries(tokens.space).filter(([k]) => !k.startsWith("$")).map(([, v]) => (v as Node).$value);
    expect(space).toEqual(["4px", "8px", "12px", "16px", "24px", "32px"]);
    const radii = Object.entries(tokens.radius).filter(([k]) => !k.startsWith("$")).map(([, v]) => parseFloat((v as Node).$value as string));
    expect(Math.max(...radii)).toBeLessThanOrEqual(8);
  });
});
