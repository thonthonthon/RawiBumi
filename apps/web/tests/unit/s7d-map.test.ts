import { beforeEach, expect, it, vi } from "vitest";
const h = vi.hoisted(() => ({ effects: [] as Array<() => unknown>, refs: [] as any[], cursor: 0, centres: [] as number[][], markers: [] as number[][] }));
vi.mock("react", async (load) => ({ ...await load<typeof import("react")>(),
  useEffect: (effect: () => unknown) => h.effects.push(effect), useState: () => [null, vi.fn()],
  useRef: (initial: unknown) => { const i = h.cursor++; if (!(i in h.refs)) h.refs[i] = { current: initial }; return h.refs[i]; }
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("maplibre-gl", () => ({
  setWorkerUrl: vi.fn(), NavigationControl: class {},
  Map: class { constructor(options: { center: number[] }) { h.centres.push(options.center); } addControl() {} on() {} setCenter(p: number[]) { h.centres.push(p); } isStyleLoaded() { return false; } remove() {} },
  Marker: class { setLngLat(p: number[]) { h.markers.push(p); return this; } addTo() { return this; } remove() {} }
}));
vi.mock("../../src/ui/palette", () => ({ token: () => "ink" }));
import { MapWorkspace, validMapCoordinates } from "../../src/MapWorkspace";
const props = (a: number, b: number) => ({ site: { latitude_deg: a, longitude_deg: b, timezone: "UTC", north_reference: "geodetic_true_north" }, geojson: { type: "FeatureCollection" as const, features: [] } });
function render(a: number, b: number) { h.cursor = 0; h.effects = []; MapWorkspace(props(a, b)); h.refs[1].current ??= {}; for (const effect of h.effects) effect(); }
beforeEach(() => { h.refs = []; h.centres = []; h.markers = []; });
it.each([[123, 106], [90, 0], [-90, 0], [0, 181], [NaN, 0], [0, Infinity]])("never supplies invalid coordinates %s/%s to MapLibre", (a, b) => {
  expect(validMapCoordinates(a, b)).toBe(false); render(a, b);
  expect(h.centres).toEqual([[0, 0]]); expect(h.markers).toEqual([[0, 0]]);
});
it("keeps its last valid view on invalid updates and accepts the next valid site", () => {
  render(-6.2, 106.8); const before = [...h.centres], markerBefore = [...h.markers];
  render(123, 106.8); expect(h.centres).toEqual(before); expect(h.markers).toEqual(markerBefore);
  render(-7.25, 108); expect(h.centres.at(-1)).toEqual([108, -7.25]); expect(h.markers.at(-1)).toEqual([108, -7.25]);
});
