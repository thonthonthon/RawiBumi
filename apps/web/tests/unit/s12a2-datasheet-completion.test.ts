import {beforeEach, expect, it, vi} from "vitest";
import {isValidElement, type ReactElement} from "react";
const h = vi.hoisted(() => ({slots: [] as any[], cursor: 0, preview: vi.fn(), save: vi.fn(), run: vi.fn(), busy: null as string | null}));
vi.mock("react", async load => ({...await load<typeof import("react")>(), useState: (value: unknown) => {
 const slot = h.cursor++; if (!(slot in h.slots)) h.slots[slot] = value;
 return [h.slots[slot], (next: unknown) => {h.slots[slot] = next;}];
}}));
vi.mock("react-i18next", async load => ({...await load<typeof import("react-i18next")>(), useTranslation: () => ({t: i18n.t.bind(i18n), i18n})}));
vi.mock("../../src/state/store", () => ({useStore: () => ({state: {busy: h.busy}, run: h.run})}));
vi.mock("../../src/client", () => ({engine: {previewComponentCompletion: h.preview, completeComponent: h.save}}));
import i18n from "../../src/i18n";
import {completionInput, componentReasonText, DatasheetCompletion} from "../../src/Modals";
import {Button} from "../../src/ui/kit";
import {api} from "../../src/api";
import {mockApi} from "../../src/demo/mockApi";
import {DemoUnavailableError} from "../../src/engine/adapter";
import type {ComponentLibraryPreview} from "../../src/types";
const CURRENT = "mppt_template.max_operating_current_a";
const base: ComponentLibraryPreview = {kind: "inverters", manufacturer: "Synthetic", model: "Test", revision_id: "lib-inv-test-r1", duplicate_of: null,
 parameters: {}, schema_ready: true, simulation_ready: false, findings: [], readiness_findings: [], reasons: [],
 completion_fields: [{path: CURRENT, unit: "A", max: 200}, {path: "ac_limits.nominal_frequency_hz", unit: "Hz", max: 60}]};
const source = {document: "Fictional datasheet", page_or_section: "Table 1", url: "https://example.com/test"};
function tree(value: unknown): ReactElement<any>[] { if (Array.isArray(value)) return value.flatMap(tree); if (!isValidElement(value)) return []; const n = value as ReactElement<any>; return [n, ...tree(n.props.children)]; }
function text(value: unknown): string {if (Array.isArray(value)) return value.map(text).join(" "); if (isValidElement(value)) return text((value as ReactElement<any>).props.children); return value == null || typeof value === "boolean" ? "" : String(value);}
const saved = vi.fn(), close = vi.fn();
function render() {h.cursor = 0; return tree(DatasheetCompletion({base, onClose: close, onSaved: saved}));}
function button(label: string) {return render().find(n => n.type === Button && text(n.props.children) === label)!;}
async function settle() {for (let i = 0; i < 30; i++) await Promise.resolve();}
beforeEach(() => {vi.clearAllMocks(); vi.unstubAllGlobals(); h.slots = []; h.busy = null; void i18n.changeLanguage("en"); h.run.mockImplementation(async (_label, op) => op()); saved.mockResolvedValue(undefined);});
it("requires a cited source and strict finite values within the allowed ranges", () => {
 expect(completionInput({[CURRENT]: "26"}, source, base)).toEqual({fields: {[CURRENT]: 26}, source});
 for (const value of ["0", "-1", "201", "NaN", "Infinity"]) expect(completionInput({[CURRENT]: value}, source, base)).toBeNull();
 expect(completionInput({}, source, base)).toBeNull();
 expect(completionInput({[CURRENT]: "26"}, {...source, document: " "}, base)).toBeNull();
 expect(completionInput({[CURRENT]: "26"}, {...source, page_or_section: ""}, base)).toBeNull();
 expect(completionInput({[CURRENT]: "26"}, {...source, url: "file:///tmp/test"}, base)).toBeNull();
 expect(completionInput({"ac_limits.nominal_frequency_hz": "55"}, source, base)).toBeNull();
 expect(button("Preview").props.disabled).toBe(true);
});
it("previews before saving, displays the citation/readiness and invalidates an edited preview", async () => {
 h.slots = [{[CURRENT]: "26"}, source];
 const result = {...base, simulation_ready: true, completed_fields: [{path: CURRENT, value: 26, unit: "A", source}]};
 h.preview.mockResolvedValue(result); h.save.mockResolvedValue({created: true, entry: result});
 expect(button("Save completed revision")).toBeUndefined();
 button("Preview").props.onClick(); await settle();
 expect(h.preview).toHaveBeenCalledWith(base.revision_id, {fields: {[CURRENT]: 26}, source}); expect(h.save).not.toHaveBeenCalled();
 expect(text(render())).toContain("Ready for simulation"); expect(text(render())).toMatch(/Fictional datasheet\s*,\s*Table 1/);
 button("Save completed revision").props.onClick(); await settle(); expect(h.save).toHaveBeenCalledWith(base.revision_id, {fields: {[CURRENT]: 26}, source}); expect(saved).toHaveBeenCalledWith(result);
 const input = render().find(n => n.type === "input" && n.props.type === "number")!;
 input.props.onChange({target: {value: "27"}}); expect(button("Save completed revision")).toBeUndefined();
});
it("busy state refuses preview and save; Cancel sends nothing", () => {
 h.slots = [{[CURRENT]: "26"}, source, base]; h.busy = "Other command";
 expect(button("Preview").props.disabled).toBe(true); expect(button("Save completed revision").props.disabled).toBe(true);
 button("Preview").props.onClick(); button("Save completed revision").props.onClick(); expect(h.preview).not.toHaveBeenCalled(); expect(h.save).not.toHaveBeenCalled();
 h.busy = null; button("Cancel").props.onClick(); expect(close).toHaveBeenCalled(); expect(h.save).not.toHaveBeenCalled();
});
it("uses service English, keyed Indonesian, and service fallback for unknown reasons", () => {
 const reason = {code: "mppt_operating_current_missing", message: "Service English retained"};
 expect(componentReasonText(reason, "en", i18n.t.bind(i18n))).toBe(reason.message);
 void i18n.changeLanguage("id"); expect(componentReasonText(reason, "id", i18n.t.bind(i18n))).toContain("arus operasi maksimum per MPPT");
 expect(componentReasonText({...reason, code: "future_reason"}, "id", i18n.t.bind(i18n))).toBe(reason.message);
 expect(componentReasonText({...reason, code: "finding"}, "id", i18n.t.bind(i18n))).toBe(reason.message);
});
it("sends explicit preview/save flags to the same completion route; demo never fakes completion", async () => {
 const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify({entry: base, created: true}), {status: 200})); vi.stubGlobal("fetch", fetch);
 const input = {fields: {[CURRENT]: 26}, source};
 await api.previewComponentCompletion(base.revision_id, input); await api.completeComponent(base.revision_id, input);
 for (const [i, dry_run] of [true, false].entries()) {const [url, options] = fetch.mock.calls[i]; expect(url).toBe(`/api/component-library/${base.revision_id}/complete`); expect(options.method).toBe("POST"); expect(JSON.parse(options.body)).toEqual({...input, dry_run});}
 await expect(mockApi.previewComponentCompletion(base.revision_id, input)).rejects.toBeInstanceOf(DemoUnavailableError);
 await expect(mockApi.completeComponent(base.revision_id, input)).rejects.toThrow("needs the engine");
});
