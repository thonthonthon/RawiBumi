import type { Vec2 } from "../../geometry";

/**
 * Typed input for the plan tools (DESIGN.md §5, UI spec B4), AutoCAD-style
 * dynamic input with the engine's conventions:
 *
 * - `x,y`       absolute point, metres
 * - `@dx,dy`    relative to the last point
 * - `d<a`       polar from the last point: distance d, bearing a (0° = north, 90° = east, clockwise),
 *               the convention of the engine's segment_azimuth_deg and set_edge_azimuth
 * - `d`         distance along the current cursor direction from the last point
 * - angles for the rotate tool: degrees, clockwise positive (the engine's rotate)
 *
 * Numbers accept arithmetic (`12-2*0.4`, parentheses) and a unit per number:
 * metres by default, or `cm` / `mm`. Angles accept `°` or `deg`.
 */

export type Typed =
  | { kind: "absolute"; p: Vec2 }
  | { kind: "relative"; d: Vec2 }
  | { kind: "polar"; distance: number; bearingDeg: number }
  | { kind: "distance"; distance: number };

export class TypedError extends Error {}

const UNITS: Record<string, number> = { m: 1, cm: 0.01, mm: 0.001 };

/** Evaluates `+ - * /`, unary minus, parentheses and unit suffixes. */
export function evalExpr(src: string, allowUnits = true): number {
  // Decimals take a point: the comma always separates x and y, so "2,5" is the point (2, 5).
  const s = src.replace(/\s+/g, "");
  let i = 0;
  const peek = () => s[i];
  const expr = (): number => {
    let v = term();
    while (peek() === "+" || peek() === "-") v = s[i++] === "+" ? v + term() : v - term();
    return v;
  };
  const term = (): number => {
    let v = factor();
    while (peek() === "*" || peek() === "/") {
      const op = s[i++];
      const r = factor();
      if (op === "/" && r === 0) throw new TypedError("Division by zero.");
      v = op === "*" ? v * r : v / r;
    }
    return v;
  };
  const factor = (): number => {
    if (peek() === "-") {
      i++;
      return -factor();
    }
    if (peek() === "+") {
      i++;
      return factor();
    }
    if (peek() === "(") {
      i++;
      const v = expr();
      if (peek() !== ")") throw new TypedError("Missing closing parenthesis.");
      i++;
      return v;
    }
    const m = /^(\d+(?:\.\d*)?|\.\d+)(mm|cm|m|°|deg)?/.exec(s.slice(i));
    if (!m) throw new TypedError(`Cannot read "${s.slice(i) || src}".`);
    i += m[0].length;
    const n = Number(m[1]);
    const unit = m[2];
    if (!unit || unit === "°" || unit === "deg") return n;
    if (!allowUnits) throw new TypedError("Angles take no length unit.");
    return n * UNITS[unit];
  };
  if (!s) throw new TypedError("Type a value.");
  const v = expr();
  if (i !== s.length) throw new TypedError(`Cannot read "${s.slice(i)}".`);
  if (!Number.isFinite(v)) throw new TypedError("The value is not a finite number.");
  return v;
}

/** Parses typed point input. `hasLast` is false before the first point is placed. */
export function parsePoint(input: string, hasLast: boolean): Typed {
  const s = input.trim();
  const relative = s.startsWith("@");
  const body = relative ? s.slice(1) : s;
  if (body.includes("<")) {
    if (!hasLast) throw new TypedError("Place the first point before a polar entry.");
    const [d, a] = body.split("<");
    const distance = evalExpr(d);
    if (distance < 0) throw new TypedError("Distance must not be negative.");
    return { kind: "polar", distance, bearingDeg: ((evalExpr(a, false) % 360) + 360) % 360 };
  }
  const parts = splitXY(body);
  if (parts) {
    const p: Vec2 = [evalExpr(parts[0]), evalExpr(parts[1])];
    if (relative) {
      if (!hasLast) throw new TypedError("Place the first point before a relative entry.");
      return { kind: "relative", d: p };
    }
    return { kind: "absolute", p };
  }
  if (!hasLast) throw new TypedError("The first point needs x,y.");
  const distance = evalExpr(body);
  if (distance <= 0) throw new TypedError("Distance must be positive.");
  return { kind: "distance", distance };
}

/** Splits `x,y` at the single top-level comma. */
function splitXY(s: string): [string, string] | null {
  let depth = 0;
  let at = -1;
  for (let i = 0; i < s.length; i++) {
    if (s[i] === "(") depth++;
    else if (s[i] === ")") depth--;
    else if (s[i] === "," && depth === 0) {
      if (at >= 0) throw new TypedError("Use one comma, between x and y.");
      at = i;
    }
  }
  return at < 0 ? null : [s.slice(0, at), s.slice(at + 1)];
}

/** Resolves typed input to a world point, from the last point and the cursor direction. */
export function resolvePoint(t: Typed, last: Vec2 | null, cursor: Vec2 | null): Vec2 {
  switch (t.kind) {
    case "absolute":
      return t.p;
    case "relative":
      return [last![0] + t.d[0], last![1] + t.d[1]];
    case "polar": {
      const a = (t.bearingDeg * Math.PI) / 180;
      return [last![0] + t.distance * Math.sin(a), last![1] + t.distance * Math.cos(a)];
    }
    case "distance": {
      const dx = (cursor?.[0] ?? last![0]) - last![0];
      const dy = (cursor?.[1] ?? last![1] + 1) - last![1];
      const l = Math.hypot(dx, dy);
      // No cursor direction yet: go north.
      const ux = l > 1e-9 ? dx / l : 0;
      const uy = l > 1e-9 ? dy / l : 1;
      return [last![0] + t.distance * ux, last![1] + t.distance * uy];
    }
  }
}

/** Parses an angle (rotate tool): degrees, clockwise positive. */
export function parseAngle(input: string): number {
  return evalExpr(input.trim(), false);
}

/** Characters that start typed input while a tool is active. */
export function startsTyped(key: string): boolean {
  return /^[0-9.@\-+(]$/.test(key);
}

/** Characters accepted while typing. */
export function typedChar(key: string): boolean {
  return /^[0-9.,@<+\-*/()cmd°eg ]$/.test(key);
}
