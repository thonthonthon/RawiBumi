import { beforeEach, expect, it, vi } from "vitest";
import { isValidElement, type ReactElement } from "react";
import i18n from "../../src/i18n";
import fixture from "./s7b-engine-fixture.json";
import { reportInputFingerprint, type ReportSnapshotInput } from "../../src/report/snapshot";

const h = vi.hoisted(() => ({ forms: {} as Record<string, unknown>, build: vi.fn(), toast: vi.fn(),
  address: { status: "looking", address: null as Record<string, unknown> | null, available: true, allowed: true }, view: {} as any }));
vi.mock("react", async (load) => ({ ...await load<typeof import("react")>(), useState: () => [null, vi.fn()], useMemo: (factory: () => unknown) => factory() }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: i18n.t.bind(i18n), i18n }), initReactI18next: { type: "3rdParty", init() {} } }));
vi.mock("../../src/client", () => ({ DEMO: false }));
vi.mock("../../src/site/useSiteAddress", () => ({ useSiteAddress: () => h.address }));
vi.mock("../../src/site/systemInfo", async (load) => ({ ...await load<typeof import("../../src/site/systemInfo")>(), useSystemInfo: () => [null] }));
vi.mock("../../src/report/build", () => ({ buildReportSnapshot: h.build }));
vi.mock("../../src/state/store", () => ({ useStore: () => ({ state: { view: h.view, entities: [], modules: [] }, toast: h.toast }),
  useForm: (key: string, initial: unknown) => { if (!(key in h.forms)) h.forms[key] = initial; return [h.forms[key], (value: unknown) => { h.forms[key] = value; }]; }
}));
import { ReportPanel } from "../../src/report/ReportPanel";
import { Button } from "../../src/ui/kit";

function tree(value: unknown): ReactElement<any>[] {
  if (Array.isArray(value)) return value.flatMap(tree);
  if (!isValidElement(value)) return [];
  const node = value as ReactElement<any>; return [node, ...tree(node.props.children)];
}
function render() { return tree(ReportPanel()); }
function button(nodes: ReactElement<any>[], text: string) { return nodes.find((n) => n.type === Button && n.props.children === text)!; }
beforeEach(async () => {
  await i18n.changeLanguage("en"); h.forms = {}; h.toast.mockReset();
  h.view = structuredClone(fixture.views.before); h.view.bundle.simulation_runs = [{ simulation_run_id: "run", summary_result: {} }];
  h.address = { status: "looking", address: null, available: true, allowed: true };
  h.build.mockReset().mockImplementation((input: ReportSnapshotInput) => ({ html: "<p>Stable report</p>", inputFingerprint: reportInputFingerprint(input), modelFingerprint: "model", snapshotId: "snapshot", generatedAt: "2026-10-30T00:00:00Z" }));
});
it.each(["idle", "failed"])("A2 refuses report generation during lookup and produces a non-stale snapshot after status=%s", (status) => {
  const nodes = render(); const preview = button(nodes, "Preview report"), download = button(nodes, "Download HTML");
  expect(preview.props.disabled).toBe(true); expect(download.props.disabled).toBe(true);
  expect(preview.props.title).toBe(i18n.t("site.looking")); expect(download.props.title).toBe(i18n.t("site.looking"));
  // A late call to either captured handler must be a no-op as well.
  preview.props.onClick(); download.props.onClick(); expect(h.build).not.toHaveBeenCalled(); expect(h.forms["report.snapshot"]).toBeNull();
  h.address.status = status;
  h.address.address = status === "idle" ? { text: "Resolved site address", attribution: "Test provider" } : null;
  const ready = render(); expect(button(ready, "Preview report").props.disabled).toBe(false); expect(button(ready, "Download HTML").props.disabled).toBe(false);
  button(ready, "Preview report").props.onClick(); expect(h.build).toHaveBeenCalledTimes(1);
  const after = render(); expect(after.some((n) => n.type === "iframe" && n.props.srcDoc === "<p>Stable report</p>")).toBe(true);
  expect(after.some((n) => n.props["data-report-stale"])).toBe(false);
  // Even an already cached snapshot must not bypass the download guard.
  h.address.status = "looking";
  const lookingAgain = render();
  button(lookingAgain, "Preview report").props.onClick(); button(lookingAgain, "Download HTML").props.onClick();
  expect(h.build).toHaveBeenCalledTimes(1);
});
