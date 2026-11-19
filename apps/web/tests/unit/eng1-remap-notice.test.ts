import { beforeEach, expect, it, vi } from "vitest";
import { isValidElement, type ReactElement } from "react";
const h = vi.hoisted(() => ({ cursor: 0, preview: null as any }));
vi.mock("react", async (load) => ({
  ...await load<typeof import("react")>(),
  useState: (initial: unknown) => {
    const slot = h.cursor++;
    return [slot === 2 ? h.preview : initial, vi.fn()];
  },
  useEffect: () => {}
}));
vi.mock("react-i18next", async (load) => ({
  ...await load<typeof import("react-i18next")>(),
  useTranslation: () => ({ t: i18n.t.bind(i18n), i18n })
}));
vi.mock("../../src/state/store", () => ({
  useStore: () => ({ state: { busy: null, view: null }, run: vi.fn(), toast: vi.fn(), dispatch: vi.fn() }),
  uiStore: { getState: () => ({ state: {} }) }
}));
vi.mock("../../src/client", () => ({ engine: {} }));
import i18n from "../../src/i18n";
import { ImportHub } from "../../src/Modals";
function text(value: unknown): string {
  if (value == null || typeof value === "boolean") return "";
  if (Array.isArray(value)) return value.map(text).join(" ");
  if (isValidElement(value)) return text((value as ReactElement<any>).props.children);
  return String(value);
}
beforeEach(() => {
  h.cursor = 0;
  void i18n.changeLanguage("en");
  h.preview = {
    kind: "inverters", manufacturer: "Synthetic", model: "ENG1", revision_id: "lib-inv-eng1-r2",
    duplicate_of: null, parameters: {}, findings: [], schema_ready: true, simulation_ready: false,
    readiness_findings: [], reasons: [{code: "mppt_operating_current_missing", message: "MPPT current is missing."}]
  };
});
it("shows the replaced revision in a separate translated remap notice, preserving readiness", () => {
  h.preview.remapped_from = "lib-inv-eng1-r1";
  const english = text(ImportHub({ onClose: vi.fn() }));
  expect(english).toContain("Re-imported with the current importer; replaces lib-inv-eng1-r1.");
  expect(english).toContain("Layout only");
  expect(english).toContain("MPPT current is missing.");
  void i18n.changeLanguage("id"); h.cursor = 0;
  expect(text(ImportHub({ onClose: vi.fn() }))).toContain("Diimpor ulang dengan pengimpor terkini; menggantikan lib-inv-eng1-r1.");
});
it("ordinary imports show no remap notice", () => {
  expect(text(ImportHub({ onClose: vi.fn() }))).not.toContain("Re-imported");
});
