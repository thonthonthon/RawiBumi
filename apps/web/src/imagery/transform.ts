import type { Vec2 } from "../geometry";

/**
 * An overlay image placed on the plan (UX1). Image pixels run right and down; local metres run east and north.
 * `offset` is the world position of the image's top-left pixel, `rotationDeg` turns the image counter-clockwise,
 * and `sx` / `sy` are metres per pixel across and down.
 */
export interface OverlayTransform { offset: Vec2; rotationDeg: number; sx: number; sy: number }
export interface ControlPoint { pixel_x: number; pixel_y: number; local_x_m: number; local_y_m: number }

const DEG = Math.PI / 180;

export function pixelToWorld(t: OverlayTransform, px: number, py: number): Vec2 {
  const c = Math.cos(t.rotationDeg * DEG), s = Math.sin(t.rotationDeg * DEG);
  return [t.offset[0] + px * t.sx * c + py * t.sy * s, t.offset[1] + px * t.sx * s - py * t.sy * c];
}

export function worldToPixel(t: OverlayTransform, w: Vec2): Vec2 {
  const c = Math.cos(t.rotationDeg * DEG), s = Math.sin(t.rotationDeg * DEG);
  const dx = w[0] - t.offset[0], dy = w[1] - t.offset[1];
  return [(dx * c + dy * s) / t.sx, (dx * s - dy * c) / t.sy];
}

/** Corners in world metres: top-left, top-right, bottom-right, bottom-left. */
export function overlayCorners(t: OverlayTransform, width: number, height: number): [Vec2, Vec2, Vec2, Vec2] {
  return [pixelToWorld(t, 0, 0), pixelToWorld(t, width, 0), pixelToWorld(t, width, height), pixelToWorld(t, 0, height)];
}

/** The persisted form: three image corners, which encode the transform exactly as an affine. */
export function toControlPoints(t: OverlayTransform, width: number, height: number): [ControlPoint, ControlPoint, ControlPoint] {
  const point = (px: number, py: number): ControlPoint => {
    const [x, y] = pixelToWorld(t, px, py);
    return { pixel_x: px, pixel_y: py, local_x_m: x, local_y_m: y };
  };
  return [point(0, 0), point(width, 0), point(0, height)];
}

/**
 * Back from control points. A least-squares affine fits any three or more points; it is read as offset, rotation and
 * the two scales (an external file's shear is not kept). rms is the fit's residual in metres.
 */
export function fromControlPoints(points: ControlPoint[]): { transform: OverlayTransform; rmsErrorM: number } {
  if (points.length < 3) throw new Error("An overlay needs at least 3 control points.");
  // Solve x = a·px + b·py + c and y = d·px + e·py + f by normal equations.
  const rows = points.map((p) => [p.pixel_x, p.pixel_y, 1]);
  const solve = (values: number[]) => leastSquares3(rows, values);
  const [a, b, c] = solve(points.map((p) => p.local_x_m));
  const [d, e, f] = solve(points.map((p) => p.local_y_m));
  const sx = Math.hypot(a, d), rotationDeg = Math.atan2(d, a) / DEG;
  const sy = Math.hypot(b, e);
  const transform = { offset: [c, f] as Vec2, rotationDeg, sx, sy };
  const residual = points.reduce((sum, p) => {
    const [x, y] = [a * p.pixel_x + b * p.pixel_y + c, d * p.pixel_x + e * p.pixel_y + f];
    return sum + (x - p.local_x_m) ** 2 + (y - p.local_y_m) ** 2;
  }, 0);
  return { transform, rmsErrorM: Math.sqrt(residual / points.length) };
}

function leastSquares3(rows: number[][], values: number[]): [number, number, number] {
  const m = [[0, 0, 0], [0, 0, 0], [0, 0, 0]], v = [0, 0, 0];
  rows.forEach((r, k) => { for (let i = 0; i < 3; i++) { v[i] += r[i] * values[k]; for (let j = 0; j < 3; j++) m[i][j] += r[i] * r[j]; } });
  const det = (q: number[][]) => q[0][0] * (q[1][1] * q[2][2] - q[1][2] * q[2][1]) - q[0][1] * (q[1][0] * q[2][2] - q[1][2] * q[2][0]) + q[0][2] * (q[1][0] * q[2][1] - q[1][1] * q[2][0]);
  const d = det(m);
  if (Math.abs(d) < 1e-12) throw new Error("The control points are collinear.");
  const col = (i: number) => det(m.map((row, r) => row.map((x, c) => (c === i ? v[r] : x))));
  return [col(0) / d, col(1) / d, col(2) / d];
}

/** Two-point calibration: scale about the first point so its distance to the second becomes `trueDistanceM`. */
export function calibrateTwoPoints(t: OverlayTransform, first: Vec2, second: Vec2, trueDistanceM: number): OverlayTransform {
  const current = Math.hypot(second[0] - first[0], second[1] - first[1]);
  if (!(trueDistanceM > 0) || !Number.isFinite(trueDistanceM)) throw new Error("Enter a positive distance.");
  if (current < 1e-9) throw new Error("Pick two different points.");
  const k = trueDistanceM / current;
  return { ...t, sx: t.sx * k, sy: t.sy * k, offset: [first[0] + (t.offset[0] - first[0]) * k, first[1] + (t.offset[1] - first[1]) * k] };
}

export function moveOverlay(t: OverlayTransform, delta: Vec2): OverlayTransform {
  return { ...t, offset: [t.offset[0] + delta[0], t.offset[1] + delta[1]] };
}

/** Rotate by `angleDeg` counter-clockwise about a world point. */
export function rotateOverlay(t: OverlayTransform, pivot: Vec2, angleDeg: number): OverlayTransform {
  const c = Math.cos(angleDeg * DEG), s = Math.sin(angleDeg * DEG);
  const dx = t.offset[0] - pivot[0], dy = t.offset[1] - pivot[1];
  return { ...t, rotationDeg: t.rotationDeg + angleDeg, offset: [pivot[0] + dx * c - dy * s, pivot[1] + dx * s + dy * c] };
}

/**
 * Drag corner `corner` (0 TL, 1 TR, 2 BR, 3 BL) to world point `to`, keeping the opposite corner fixed.
 * `keepAspect` (Shift) scales both axes by the same factor.
 */
export function scaleFromCorner(t: OverlayTransform, width: number, height: number, corner: number, to: Vec2, keepAspect: boolean): OverlayTransform {
  const pixel: Vec2[] = [[0, 0], [width, 0], [width, height], [0, height]];
  const anchor = pixel[(corner + 2) % 4];
  const fixed = pixelToWorld(t, anchor[0], anchor[1]);
  const p = worldToPixel(t, to);
  // Signed size of the dragged rectangle in pixels of the old transform, measured from the fixed corner.
  const dir: Vec2 = [Math.sign(pixel[corner][0] - anchor[0]), Math.sign(pixel[corner][1] - anchor[1])];
  let fx = Math.max(1e-3, ((p[0] - anchor[0]) * dir[0]) / width);
  let fy = Math.max(1e-3, ((p[1] - anchor[1]) * dir[1]) / height);
  if (keepAspect) fx = fy = Math.max(fx, fy);
  const next = { ...t, sx: t.sx * fx, sy: t.sy * fy };
  // Keep the fixed corner in place.
  const moved = pixelToWorld(next, anchor[0], anchor[1]);
  return moveOverlay(next, [fixed[0] - moved[0], fixed[1] - moved[1]]);
}
