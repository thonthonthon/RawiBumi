import { expect, it, vi } from "vitest";
import { isValidElement, type ReactElement } from "react";
import i18n from "../../src/i18n";
import fixture from "./s7b-engine-fixture.json";
import { ReportPanel } from "../../src/report/ReportPanel";

const ui = vi.hoisted(() => ({ view: {} as any, build: vi.fn(), error: vi.fn(), toast: vi.fn() }));
vi.mock("react", async load => ({ ...await load<typeof import("react")>(),
  useState: () => [null, ui.error], useMemo: (factory: () => unknown) => factory() }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: i18n.t.bind(i18n), i18n }),
  initReactI18next: { type: "3rdParty", init() {} } }));
vi.mock("../../src/client", () => ({ DEMO: false }));
vi.mock("../../src/site/useSiteAddress", () => ({ useSiteAddress: () => ({ status: "idle", address: null }) }));
vi.mock("../../src/site/systemInfo", async load => ({ ...await load<typeof import("../../src/site/systemInfo")>(), useSystemInfo: () => [null] }));
vi.mock("../../src/report/build", () => ({ buildReportSnapshot: ui.build }));
vi.mock("../../src/state/store", () => ({
  useStore: () => ({ state: { view: ui.view, entities: [], modules: [] }, toast: ui.toast }),
  useForm: (key: string, initial: unknown) => [key === "report.snapshot" ? null : initial, vi.fn()]
}));

type Node = ReactElement<{ children?: unknown; disabled?: boolean; onClick?: () => void }>;
function nodes(value: unknown): Node[] {
  if (Array.isArray(value)) return value.flatMap(nodes);
  if (!isValidElement(value)) return [];
  const node = value as Node; return [node, ...nodes(node.props.children)];
}
it("keeps Preview clickable after the server's earlier-design refusal and shows the existing message without building a report", async () => {
  await i18n.changeLanguage("en"); ui.view = structuredClone(fixture.views.before);
  ui.view.bundle.simulation_runs = [{ simulation_run_id: "synthetic-run", summary_result: {} }];
  const tree = nodes(ReportPanel({ verifiedSource: null, snapshotError: "earlier_design: the report needs the design that this run simulated" }));
  const preview = tree.find(node => node.props.children === "Preview report")!;
  expect(preview.props.disabled).toBe(false);
  preview.props.onClick!();
  expect(ui.error).toHaveBeenCalledWith("This run is from an earlier design. Run the simulation again to make a report.");
  expect(ui.build).not.toHaveBeenCalled();
});
