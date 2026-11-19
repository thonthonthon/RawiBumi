import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Vec2 } from "../../src/geometry";
import { imageryConfig, initialOverlay, parseImagery, satelliteFrom } from "../../src/imagery/config";
import { imageHeader, MAX_IMAGE_BYTES } from "../../src/imagery/header";
import { CREDENTIAL_REFERENCE, loadKey, loadProvider, providerReady, saveKey, saveProvider, templateProblem, tileUrl } from "../../src/imagery/provider";
import { calibrateTwoPoints, fromControlPoints, moveOverlay, overlayCorners, pixelToWorld, rotateOverlay, scaleFromCorner, toControlPoints, worldToPixel, type OverlayTransform } from "../../src/imagery/transform";
import { buildMenu, type MenuState } from "../../src/canvas/contextMenu";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import i18n from "../../src/i18n";
import { TOOLS } from "../../src/canvas/tools";

const near = (a: Vec2, b: Vec2) => { expect(a[0]).toBeCloseTo(b[0], 9); expect(a[1]).toBeCloseTo(b[1], 9); };
const t0: OverlayTransform = { offset: [3, 20], rotationDeg: 30, sx: 0.05, sy: 0.07 };

function png(width: number, height: number, pad = 0) {
  const b = new Uint8Array(24 + pad);
  b.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13, 0x49, 0x48, 0x44, 0x52]);
  new DataView(b.buffer).setUint32(16, width); new DataView(b.buffer).setUint32(20, height);
  return b;
}

it("transform: pixels and metres round-trip, corners follow rotation, and three control points encode it exactly", () => {
  for (const p of [[0, 0], [400, 0], [0, 300], [123.5, 77.25]] as Vec2[]) near(worldToPixel(t0, pixelToWorld(t0, p[0], p[1])), p);
  near(pixelToWorld({ ...t0, rotationDeg: 0 }, 100, 0), [3 + 5, 20]);
  near(pixelToWorld({ ...t0, rotationDeg: 0 }, 0, 100), [3, 20 - 7]);
  near(pixelToWorld({ ...t0, rotationDeg: 90 }, 100, 0), [3, 20 + 5]);
  const back = fromControlPoints(toControlPoints(t0, 400, 300));
  expect(back.rmsErrorM).toBeLessThan(1e-9);
  near(back.transform.offset, t0.offset);
  expect(back.transform.rotationDeg).toBeCloseTo(30, 9); expect(back.transform.sx).toBeCloseTo(0.05, 12); expect(back.transform.sy).toBeCloseTo(0.07, 12);
  expect(() => fromControlPoints(toControlPoints(t0, 400, 300).slice(0, 2))).toThrow("at least 3");
  const corners = overlayCorners(t0, 400, 300);
  near(corners[2], pixelToWorld(t0, 400, 300));
});

it("calibration, move, rotate and corner scaling keep the right point fixed", () => {
  const a = pixelToWorld(t0, 50, 40), b = pixelToWorld(t0, 250, 40);
  const cal = calibrateTwoPoints(t0, a, b, 20);
  near(pixelToWorld(cal, 50, 40), a);
  const a2 = pixelToWorld(cal, 50, 40), b2 = pixelToWorld(cal, 250, 40);
  expect(Math.hypot(b2[0] - a2[0], b2[1] - a2[1])).toBeCloseTo(20, 9);
  expect(cal.sx / cal.sy).toBeCloseTo(t0.sx / t0.sy, 12);
  expect(() => calibrateTwoPoints(t0, a, a, 5)).toThrow("two different points");
  expect(() => calibrateTwoPoints(t0, a, b, 0)).toThrow("positive distance");
  near(moveOverlay(t0, [1, -2]).offset, [4, 18]);
  const pivot = pixelToWorld(t0, 200, 150);
  const r = rotateOverlay(t0, pivot, 45);
  expect(r.rotationDeg).toBeCloseTo(75, 12); near(pixelToWorld(r, 200, 150), pivot);
  const fixed = pixelToWorld(t0, 0, 300);
  const stretched = scaleFromCorner(t0, 400, 300, 1, pixelToWorld(t0, 800, -150), false);
  near(pixelToWorld(stretched, 0, 300), fixed);
  expect(stretched.sx).toBeCloseTo(0.1, 9); expect(stretched.sy).toBeCloseTo(0.07 * 1.5, 9);
  const kept = scaleFromCorner(t0, 400, 300, 1, pixelToWorld(t0, 800, -150), true);
  expect(kept.sx / kept.sy).toBeCloseTo(t0.sx / t0.sy, 12);
  near(pixelToWorld(kept, 0, 300), fixed);
});

it("the persisted configuration never carries the key and round-trips both layers", () => {
  const provider = { name: "Mine", tileUrlTemplate: "https://t.example/{z}/{x}/{y}.jpg?key={key}", attribution: "© Example", termsAccepted: true };
  const overlay = { ...initialOverlay({ asset_id: "img-abc", filename: "roof.png", width_px: 400, height_px: 300 }), transform: t0, locked: true, opacity: 0.6 };
  const config = imageryConfig({ satellite: satelliteFrom(provider, 0.7), overlay })!;
  expect(JSON.stringify(config)).not.toContain("secret");
  expect(config.providers[0]).toMatchObject({ provider_kind: "xyz_raster", credential_reference: CREDENTIAL_REFERENCE, tile_url_template: provider.tileUrlTemplate });
  const parsed = parseImagery(config);
  expect(parsed.satellite).toMatchObject({ opacity: 0.7, attribution: "© Example" });
  expect(parsed.overlay).toMatchObject({ assetId: "img-abc", width: 400, height: 300, locked: true, opacity: 0.6 });
  expect(parsed.overlay!.transform.rotationDeg).toBeCloseTo(30, 9);
  expect(imageryConfig({ satellite: null, overlay: null })).toBeNull();
  expect(parseImagery(null)).toEqual({ satellite: null, overlay: null });
  const first = initialOverlay({ asset_id: "img-x", filename: "a.png", width_px: 200, height_px: 100 });
  near(pixelToWorld(first.transform, 100, 50), [0, 0]);
});

it("headers: limits, formats and the 8,192 px edge, without decoding", () => {
  expect(imageHeader(png(400, 300))).toEqual({ mime: "image/png", width: 400, height: 300 });
  expect(imageHeader(png(8192, 8192))).toMatchObject({ width: 8192 });
  expect(imageHeader(png(8193, 1))).toEqual({ problem: "imagery.tooManyPixels" });
  expect(imageHeader(png(10, 10, MAX_IMAGE_BYTES - 24))).toMatchObject({ mime: "image/png" });
  expect(imageHeader(png(10, 10, MAX_IMAGE_BYTES - 23))).toEqual({ problem: "imagery.tooLarge" });
  expect(imageHeader(new TextEncoder().encode("GIF89a...."))).toEqual({ problem: "imagery.unsupported" });
  expect(imageHeader(new TextEncoder().encode("<svg/>"))).toEqual({ problem: "imagery.unsupported" });
  expect(imageHeader(png(1, 1).slice(0, 12))).toEqual({ problem: "imagery.badHeader" });
  const jpeg = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0, 4, 0, 0, 0xff, 0xc0, 0, 11, 8, 0x01, 0xe0, 0x02, 0x80, 1, 1, 0x11, 0]);
  expect(imageHeader(jpeg)).toEqual({ mime: "image/jpeg", width: 640, height: 480 });
});

beforeEach(() => { saveProvider(null); saveKey(""); });
afterEach(() => { vi.unstubAllGlobals(); });

it("provider rules mirror the engine, and storage failures fall back to memory", () => {
  expect(templateProblem("http://t/{z}/{x}/{y}")).toBe("imagery.needsHttps");
  expect(templateProblem("https://t/{z}/{x}")).toBe("imagery.needsZxy");
  expect(templateProblem("https://t/{z}/{x}/{y}?key=abc123")).toBe("imagery.literalKey");
  expect(templateProblem("https://t/{z}/{x}/{y}?access_token={key}")).toBeNull();
  expect(tileUrl("https://t/{z}/{x}/{y}?k={key}", 3, 4, 5, "a b")).toBe("https://t/3/4/5?k=a%20b");
  const p = { name: "Mine", tileUrlTemplate: "https://t/{z}/{x}/{y}?k={key}", attribution: "©", termsAccepted: true };
  expect(providerReady(p, "")).toBe(false);
  expect(providerReady(p, "k")).toBe(true);
  expect(providerReady({ ...p, termsAccepted: false }, "k")).toBe(false);
  expect(providerReady({ ...p, tileUrlTemplate: "https://t/{z}/{x}/{y}.png" }, "")).toBe(true);
  vi.stubGlobal("window", { localStorage: { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); }, removeItem: () => { throw new Error("blocked"); } }, dispatchEvent: () => true });
  saveProvider(p); saveKey("secret-key");
  expect(loadProvider()).toEqual(p);
  expect(loadKey()).toBe("secret-key");
});

it("the plan menu offers overlay lock, unlock and calibrate on the empty canvas", async () => {
  await i18n.changeLanguage("en");
  const base: MenuState = { target: { kind: "empty" }, selected: [], selectedModules: 0, activeTables: 0, step: "scene", busy: false, canUndo: false, canRedo: false, tools: TOOLS, anyVisible: true, meshIds: new Set() };
  const ids = (s: MenuState) => buildMenu(s, (k, o) => i18n.t(k, o)).map((i) => i.id);
  expect(ids(base)).not.toContain("overlayLock");
  expect(ids({ ...base, overlay: "locked" })).toContain("overlayUnlock");
  expect(ids({ ...base, overlay: "unlocked" })).toEqual(expect.arrayContaining(["overlayCalibrate", "overlayLock"]));
});

it("the demo engine stores an overlay, refuses unknown assets and literal keys, and undoes imagery", async () => {
  setDemoLatency(0);
  const asset = await mockApi.uploadImageryAsset("demo-project", new Blob([png(400, 300)]), "roof.png");
  expect(asset).toMatchObject({ width_px: 400, height_px: 300, mime: "image/png" });
  await expect(mockApi.uploadImageryAsset("demo-project", new Blob([new TextEncoder().encode("GIF89a")]), "x.gif")).rejects.toMatchObject({ status: 422 });
  const config = imageryConfig({ satellite: null, overlay: initialOverlay(asset) })!;
  const saved = await mockApi.updateImagery("demo-project", config);
  expect(saved.bundle.imagery).toEqual(config);
  await expect(mockApi.updateImagery("demo-project", imageryConfig({ satellite: null, overlay: { ...initialOverlay(asset), assetId: "img-missing" } }))).rejects.toMatchObject({ status: 422 });
  const literal = imageryConfig({ satellite: { name: "x", template: "https://t/{z}/{x}/{y}?key=abc", attribution: "©", credentialReference: CREDENTIAL_REFERENCE, opacity: 1 }, overlay: null });
  await expect(mockApi.updateImagery("demo-project", literal)).rejects.toMatchObject({ status: 422 });
  const undone = await mockApi.undo("demo-project", { expected_project_revision_id: saved.bundle.project.project_revision.project_revision_id, expected_entry_id: "demo" });
  expect(undone.bundle.imagery).toBeUndefined();
});
