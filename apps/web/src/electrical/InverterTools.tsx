import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { engine } from "../client";
import { engineCommand } from "../state/history";
import { useStore } from "../state/store";
import type { TopologyChecks } from "../engine/topology";
import type { CatalogInverter, InverterLifecycleResult, MpptLayoutSuggestion, ProjectView } from "../types";
import { Button, Select, StatusDot } from "../ui/kit";
import { pickable, useShowTestComponents } from "../ui/testComponents";
import { CompleteFromDatasheet, readinessLabelKey } from "./ComponentActions";
import { formatNotation, type MpptLayout } from "./notation";

type Inverter = ProjectView["bundle"]["electrical_design"]["inverter_instances"][number];

/** USE1 (E7, C1, E9): the inverter's revision and readiness, and Switch / Complete / Change model / Remove. */
export function InverterLifecycle({ inv, def }: { inv: Inverter; def: CatalogInverter | undefined }) {
  const { t } = useTranslation();
  const { state, toast } = useStore();
  const v = state.view!;
  const pid = v.bundle.project.project_id;
  const [showTest] = useShowTestComponents();
  const [changing, setChanging] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  const assigned = v.topology_view.inverters.find((i) => i.inverter_instance_id === inv.inverter_instance_id)?.mppts.flatMap((m) => m.strings.map((s) => s.string_id)) ?? [];
  const report = (r: (ProjectView & { command_results?: InverterLifecycleResult[] }) | null | undefined) => {
    const released = r?.command_results?.[0]?.unassigned_string_ids ?? [];
    if (r && released.length) toast("info", t("use1.unassigned", { count: released.length, strings: released.join(", ") }));
  };
  const change = async (revision: string) => {
    report(await engineCommand(t("use1.changing"), () => engine.changeInverter(pid, inv.inverter_instance_id, revision)));
    setChanging(null);
  };
  const options = pickable(v.catalog.inverters, showTest).filter((c) => c.revision_id !== inv.inverter_definition_revision_id);
  return (
    <div className="inv-lifecycle" data-inverter-lifecycle={inv.inverter_instance_id}>
      <div className="row wrap">
        <span className="tag" title={inv.inverter_definition_revision_id}>{inv.inverter_definition_revision_id}</span>
        <span className={def?.simulation_ready === false ? "tag tag--warn" : "tag"} data-readiness={def?.simulation_ready === false ? "needs_values" : "ready"}>
          {t(readinessLabelKey(def))}
        </span>
      </div>
      {def?.superseded_by && (
        <div className="row wrap" role="status">
          <span className="sub">{t("use1.completedAvailable")}</span>
          <Button small tone="primary" disabled={!!state.busy} onClick={() => void change(def.superseded_by!)}>{t("use1.switchCompleted")}</Button>
        </div>
      )}
      {def?.simulation_ready === false && !def.superseded_by && (
        <div className="row wrap" role="status">
          <span className="sub">{t("use1.needsValuesNote")}</span>
          <CompleteFromDatasheet revisionId={inv.inverter_definition_revision_id} />
        </div>
      )}
      <div className="row wrap">
        {changing === null ? (
          <Button small disabled={!!state.busy || !options.length} onClick={() => setChanging(options[0]?.revision_id ?? "")}>{t("use1.changeModel")}</Button>
        ) : (
          <>
            <Select label={t("use1.newModel")} value={changing} onChange={setChanging}
              options={options.map((c) => ({ value: c.revision_id, label: `${c.model} · ${c.mppt_count} MPPT · ${t(readinessLabelKey(c))}` }))} />
            <Button small tone="primary" disabled={!!state.busy || !changing} onClick={() => void change(changing)}>{t("use1.change")}</Button>
            <Button small cancel onClick={() => setChanging(null)}>{t("hardening.cancel")}</Button>
          </>
        )}
        {!removing ? (
          <Button small disabled={!!state.busy} onClick={() => setRemoving(true)}>{t("use1.remove")}</Button>
        ) : (
          <span className="row wrap" role="alert">
            <span className="sub">{t("use1.removeConfirm", { name: inv.name, count: assigned.length })}</span>
            <Button small tone="danger" disabled={!!state.busy} onClick={async () => {
              report(await engineCommand(t("use1.removing"), () => engine.removeInverter(pid, inv.inverter_instance_id)));
              setRemoving(false);
            }}>{t("use1.remove")}</Button>
            <Button small cancel onClick={() => setRemoving(false)}>{t("hardening.cancel")}</Button>
          </span>
        )}
      </div>
    </div>
  );
}

/** USE1 (E4, USE-D2): ask the engine for a validated layout; it lands in the notation as a draft to review and Apply. */
export function SuggestStringing({ inv, pairedFieldIds, onLayout }: { inv: Inverter; pairedFieldIds: string[]; onLayout: (layout: MpptLayout, replaceStringIds: string[]) => void }) {
  const { t } = useTranslation();
  const { state, toast } = useStore();
  const [result, setResult] = useState<MpptLayoutSuggestion | null>(null);
  const [loading, setLoading] = useState(false);
  const pid = state.view!.bundle.project.project_id;
  const ask = async () => {
    setLoading(true);
    try {
      const r = await engine.suggestLayout(pid, inv.inverter_instance_id, pairedFieldIds);
      setResult(r);
      if (r.status === "suggestion_available" && r.layout) onLayout({ mppts: r.layout }, r.replace_string_ids ?? []);
    } catch (err) {
      toast("error", err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };
  const clipping = result?.warnings?.some((w) => w.rule_id === "MPPT_OPERATING_CURRENT_EXCEEDED");
  return (
    <div className="suggest" data-suggest={inv.inverter_instance_id}>
      <Button small tone="primary" disabled={!!state.busy || loading} onClick={() => void ask()}>{loading ? t("use1.suggesting") : t("use1.suggest")}</Button>
      {result?.status === "suggestion_available" && (
        <p className="sub" role="status" data-suggest-result="available">
          {t("use1.suggested", { notation: formatNotation({ mppts: result.layout! }), used: result.modules_used, left: result.modules_left })}
          {clipping && <> {t("use1.clippingNote")}</>}
          {!!result.replace_string_ids?.length && <> {t("use1.restringNote", { count: result.replace_string_ids.length })}</>}
        </p>
      )}
      {result?.status === "no_solution" && (
        <p className="issue issue--blocking" role="alert" data-suggest-result="none">{result.reasons.map((r) => r.message).join(" ")}</p>
      )}
    </div>
  );
}

type CheckState = "pass" | "warn" | "fail" | "unavailable";
const ORDER: Record<CheckState, number> = { fail: 3, warn: 2, unavailable: 1, pass: 0 };

/** USE1 (E5): the engine's voltage and current checks on a dry run of the draft layout, before Apply. */
export function EngineDraftChecks({ inverterId, layout, pairedFieldIds, text, replace = [], sources, onOrientationMismatch }: { inverterId: string; layout: MpptLayout | null; pairedFieldIds: string[]; text: string; replace?: string[]; sources?: (string[] | null)[] | null; onOrientationMismatch?: (mppts: number[]) => void }) {
  const { t } = useTranslation();
  const { state } = useStore();
  const pid = state.view!.bundle.project.project_id;
  const [rows, setRows] = useState<{ id: string; state: CheckState; detail: string }[] | null>(null);
  useEffect(() => {
    if (!layout) { setRows(null); return; }
    let live = true;
    const timer = window.setTimeout(async () => {
      try {
        // The same commands Apply will send: a suggested restring first removes the strings it replaces.
        const r = await engine.electricalDryRun(pid, [
          ...(replace.length ? [{ command_type: "delete_strings", parameters: { string_ids: replace } }] : []),
          { command_type: "apply_mppt_layout", parameters: { inverter_instance_id: inverterId, layout: layout.mppts, pv_field_ids: pairedFieldIds, ...(replace.length ? {} : { release_modules: true }), ...(sources === undefined ? {} : { sources }) } }]);
        const mine = new Set(r.topology_view.inverters.find((i) => i.inverter_instance_id === inverterId)?.mppts.flatMap((m) => m.strings.map((s) => s.string_id)) ?? []);
        if (live) {
          setRows(summarize(r.topology_checks, mine));
          const mixed = new Set(r.topology_checks.strings.filter(s => s.checks.some(c => c.code === "orientation" && (c.state === "warn" || c.state === "fail"))).map(s => s.string_id));
          onOrientationMismatch?.(r.topology_view.inverters.find(i => i.inverter_instance_id === inverterId)?.mppts.flatMap((m, i) => m.strings.some(s => mixed.has(s.string_id)) ? [i] : []) ?? []);
        }
      } catch (err) {
        if (live) setRows([{ id: "engine", state: "unavailable", detail: err instanceof Error ? err.message : String(err) }]);
      }
    }, 400);
    return () => { live = false; window.clearTimeout(timer); };
  }, [pid, inverterId, text, pairedFieldIds.join(","), replace.join(","), JSON.stringify(sources)]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!rows) return null;
  return (
    <ul className="checklist" data-engine-checks={inverterId}>
      {rows.map((c) => (
        <li key={c.id} data-check={c.id} data-state={c.state}>
          <StatusDot state={c.state} />
          <span className="checklist__label">{t(`use1.check.${c.id}`)}</span>
          <span className="checklist__detail">{c.detail}</span>
        </li>
      ))}
    </ul>
  );
}

function summarize(checks: TopologyChecks, strings: Set<string>) {
  const out: { id: string; state: CheckState; detail: string }[] = [];
  for (const id of ["max_voltage", "voltage_window", "current"]) {
    const found = checks.strings.filter((s) => strings.has(s.string_id)).flatMap((s) => s.checks.filter((c) => c.code === id));
    if (!found.length) continue;
    const worst = found.reduce((a, b) => (ORDER[b.state as CheckState] > ORDER[a.state as CheckState] ? b : a));
    out.push({ id, state: worst.state as CheckState, detail: worst.message });
  }
  return out;
}
