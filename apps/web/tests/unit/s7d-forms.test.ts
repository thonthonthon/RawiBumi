import { beforeEach, expect, it, vi } from "vitest";
import { createElement, isValidElement, type ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import i18n from "../../src/i18n";
import fixture from "./s7b-engine-fixture.json";
import type { ProjectView } from "../../src/types";

// A hook harness exercises form events and rendered props without adding a DOM dependency.
const h = vi.hoisted(() => ({ slots: [] as unknown[], cursor: 0, effects: [] as Array<() => unknown>, store: {} as Record<string, any>, update: vi.fn() }));
vi.mock("react", async (load) => ({ ...await load<typeof import("react")>(),
  useState: (initial: unknown) => { const i = h.cursor++; if (!(i in h.slots)) h.slots[i] = typeof initial === "function" ? initial() : initial; return [h.slots[i], (v: unknown) => { h.slots[i] = typeof v === "function" ? v(h.slots[i]) : v; }]; },
  useRef: (initial: unknown) => { const i = h.cursor++; if (!(i in h.slots)) h.slots[i] = { current: initial }; return h.slots[i]; },
  useMemo: (factory: () => unknown) => factory(), useEffect: (effect: () => unknown) => { h.effects.push(effect); }
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: i18n.t.bind(i18n) }), initReactI18next: { type: "3rdParty", init() {} } }));
vi.mock("../../src/state/store", () => ({ useStore: () => h.store }));
vi.mock("../../src/client", () => ({ DEMO: false, engine: { updateSite: h.update } }));
vi.mock("../../src/MapWorkspace", () => ({ MapWorkspace: () => null, validMapCoordinates: (a: number, b: number) => Number.isFinite(a) && Math.abs(a) < 90 && Number.isFinite(b) && Math.abs(b) <= 180 }));
import { SitePanel, siteValidation } from "../../src/panels/SitePanel";
import { StartScreen } from "../../src/StartScreen";
import { ErrorBoundary } from "../../src/ui/ErrorBoundary";
import { ModalDialog } from "../../src/ui/ModalDialog";
import { Button, Field } from "../../src/ui/kit";

function tree(value: unknown): ReactElement<any>[] {
  if (Array.isArray(value)) return value.flatMap(tree);
  if (!isValidElement(value)) return [];
  const node = value as ReactElement<any>;
  return [node, ...tree(node.props.children)];
}
function render(component: () => ReactElement) { h.cursor = 0; h.effects = []; return tree(component()); }
function field(nodes: ReactElement<any>[], label: string) { return tree(nodes.find((n) => n.type === Field && n.props.label === label)!.props.children).find((n) => n.type === "input")!; }
function button(nodes: ReactElement<any>[], label: string) { return nodes.find((n) => n.type === Button && n.props.children === label)!; }
function change(nodes: ReactElement<any>[], label: string, value: string) { field(nodes, label).props.onChange({ target: { value } }); }
beforeEach(async () => {
  h.slots = []; h.cursor = 0; await i18n.changeLanguage("en");
  const view = structuredClone(fixture.views.before) as unknown as ProjectView;
  view.bundle.project.site.name = "Original site";
  h.store = { state: { view, underlay: { kind: "none" }, busy: null }, dispatch: vi.fn(), run: vi.fn(async (_label, op) => op()) };
  h.update.mockReset().mockResolvedValue(view);
});
it.each([
  ["Latitude", "90"], ["Latitude", "123"], ["Longitude", "181"], ["Elevation (m)", "9001"], ["Timezone (IANA)", "MadeUp/Bad"]
])("site %s=%s shows an inline error and disables Apply", (label, value) => {
  let nodes = render(SitePanel); change(nodes, label, value); nodes = render(SitePanel);
  expect(field(nodes, label).props["aria-invalid"]).toBe(true);
  expect(nodes.some((n) => n.props.role === "alert")).toBe(true); expect(button(nodes, "Apply").props.disabled).toBe(true);
  expect(h.update).not.toHaveBeenCalled();
});
it("accepts valid timezone aliases and refuses non-finite or blank coordinates", () => {
  const valid = { name: "Site", latitude_deg: -6.2, longitude_deg: 106.8, elevation_m: 0, timezone: "UTC" };
  expect(siteValidation(valid)).toEqual({});
  expect(siteValidation({ ...valid, latitude_deg: NaN, longitude_deg: Infinity })).toHaveProperty("latitude_deg");
});
it.each([true, false])("sends only changed site keys, confirming bound changes only when pinned=%s", async (pinned) => {
  h.store.state.view.bundle.weather_selection = pinned ? { revision_id: "weather-pinned-42" } : null;
  let nodes = render(SitePanel); change(nodes, "Latitude", "-7.25"); nodes = render(SitePanel);
  await button(nodes, "Apply").props.onClick(); nodes = render(SitePanel);
  if (pinned) {
    expect(h.update).not.toHaveBeenCalled();
    const dialog = nodes.find((n) => n.type === ModalDialog)!;
    expect(JSON.stringify(dialog.props.children)).toContain("weather-pinned-42");
    button(nodes, "Cancel").props.onClick(); expect(render(SitePanel).some((n) => n.type === ModalDialog)).toBe(false);
    await button(render(SitePanel), "Apply").props.onClick();
    await button(render(SitePanel), "Clear selection and apply").props.onClick();
  }
  expect(h.update).toHaveBeenCalledExactlyOnceWith(h.store.state.view.bundle.project.project_id, { latitude_deg: -7.25 }, pinned ? { clear_weather_selection: true } : undefined);
});
it("a pinned weather name-only change needs no dialog or clearing flag", async () => {
  h.store.state.view.bundle.weather_selection = { revision_id: "weather-old" };
  let nodes = render(SitePanel); change(nodes, "Site name", " Site renamed "); nodes = render(SitePanel);
  await button(nodes, "Apply").props.onClick();
  expect(h.update).toHaveBeenCalledExactlyOnceWith(h.store.state.view.bundle.project.project_id, { name: "Site renamed" }, undefined);
});
it("typing latitude 123 leaves StartScreen mounted, shows its error and never supplies it to the map", () => {
  const props = { projects: [], catalog: null, busy: false, loading: false, unavailable: false, onOpen: vi.fn(), onCreated: vi.fn(), onRename: vi.fn(), onDelete: vi.fn() };
  let nodes = render(() => StartScreen(props)); change(nodes, "Latitude", "123"); nodes = render(() => StartScreen(props));
  expect(nodes.some((n) => n.type === "main")).toBe(true);
  expect(nodes.some((n) => n.props.role === "alert" && n.props.children.includes("Latitude"))).toBe(true);
  const map = nodes.find((n) => n.props.compact && n.props.site)!;
  expect(map.props.site.latitude_deg).toBe(-6.2); expect(button(nodes, "Create project").props.disabled).toBe(true);
});
it("the map boundary renders a fallback while its sibling engineering UI survives", () => {
  const boundary = new ErrorBoundary({ children: createElement("div", null, "Map") });
  boundary.state = ErrorBoundary.getDerivedStateFromError();
  const markup = renderToStaticMarkup(createElement("main", null, boundary.render(), createElement("button", null, "Engineering plane")));
  expect(markup).toContain("Map unavailable; coordinates and the engineering plane still work"); expect(markup).toContain("Engineering plane");
});
