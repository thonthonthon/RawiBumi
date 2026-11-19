import { modulePlacement, isExplicitField, isGeneratedField, moduleNameplateW } from "../types";
import { componentCatalogLabel } from "../types";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { DEMO, engine } from "../client";
import { checkLayout, formatNotation, MpptLayout, parseNotation, stringCount, totalModules } from "../electrical/notation";
import { layoutOfInverter, lengthsPerMppt } from "../electrical/sync";
import { TopologyTree } from "../electrical/TopologyTree";
import { ELECTRICAL_TOOLS } from "../canvas/tools";
import { slotOf } from "../engine/layout";
import type { StringOrdering, TopologyCommand } from "../engine/topology";
import { normalAngleDeg } from "../geometry";
import { GlyphBlocked, GlyphWarning } from "../ui/icons";
import { useForm, useStore } from "../state/store";
import { modulesPerField } from "../state/derived";
import { Button, Check, Field, FieldGroup, fmt, NotWired, NumberInput, Section, Segmented, Select, StatusDot } from "../ui/kit";
import { engineCommand } from "../state/history";
import { EngineDraftChecks, InverterLifecycle, SuggestStringing } from "../electrical/InverterTools";
import { useShowTestComponents } from "../ui/testComponents";
import { ComponentFilterBar, filterComponents, NO_FILTER } from "../ui/ComponentFilter";

export function ElectricalPanel() {
  const { state, dispatch, toast } = useStore();
  const v = state.view!;
  const pid = v.bundle.project.project_id;
  const [showTest, setShowTest] = useShowTestComponents();
  const [invFilter, setInvFilter] = useState(NO_FILTER);
  const addable = filterComponents(v.catalog.inverters, invFilter, showTest);
  const [add, setAdd] = useForm("elec.add", { def: addable[0]?.revision_id ?? "", name: `INV-${String(v.bundle.electrical_design.inverter_instances.length + 1).padStart(2, "0")}` });
  const [uni, setUni] = useForm("elec.uniform", { len: 16, field: "", remainder: false, ordering: "row_major" as StringOrdering });
  const [buffers, setBuffers] = useForm<Record<string, string>>("elec.notationBuffer", {});
  const topo = (command: TopologyCommand, label: string) => engineCommand(label, () => engine.topologyCommand(pid, command, v));
  const target = state.target ? v.topology_view.inverters.flatMap((i) => i.mppts.map((m) => ({ inv: i.name, m }))).find((x) => x.m.mppt_instance_id === state.target) : undefined;
  // The selection on the plan: modules, the strings it fully covers, and the tables it touches.
  const selSet = new Set(state.selection);
  const selModules = state.modules.filter((m) => selSet.has(m.id));
  const selStrings = v.bundle.electrical_design.strings.filter((x) => x.module_instance_ids.length && x.module_instance_ids.every((m) => selSet.has(m))).map((x) => x.string_id);
  // Replicate (S14b) works on tables: the demo's layout tables, or the engine's explicit tables (per field).
  const selTable = selModules.map((m): { field: string; table: string } | null => {
    const demo = slotOf(m.id);
    if (demo) return { field: m.fieldId, table: demo.tableId };
    const placed = modulePlacement(v, m.id);
    return placed?.tableId ? { field: placed.field.pv_field_id, table: placed.tableId } : null;
  }).find(Boolean) ?? null;
  const policy = v.bundle.electrical_design.orientation_policy;
  const engineTol = policy?.normal_angle_tolerance_deg ?? 1;
  const overrideOf = (mpptId: string | undefined) => policy?.overrides?.find((o) => o.mppt_instance_id === mpptId)?.reason ?? null;
  const [reasonDraft, setReasonDraft] = useState<Record<string, string>>({});
  const [overrideOpen, setOverrideOpen] = useState<Record<string, boolean>>({});
  const unstrungSel = selModules.filter((m) => !m.stringId).map((m) => m.id);
  const [tolDraft, setTolDraft] = useState<number | null>(null);
  // USE1: a suggested restring, applied in one commit while the draft is still that suggestion.
  const [restring, setRestring] = useState<Record<string, { text: string; replace: string[] }>>({});
  const tol = engineTol;
  const commitTol = () => {
    if (tolDraft === null) return;
    const next = tolDraft;
    setTolDraft(null);
    if (next !== engineTol && next >= 0 && next <= 1) void topo({ command_type: "set_orientation_tolerance", parameters: { tolerance_deg: next } }, t("electrical.settingTolerance"));
    else if (next < 0 || next > 1) toast("error", t("electrical.toleranceRange"));
  };
  const perField = modulesPerField(state);
  const { t } = useTranslation();
  const inverters = v.bundle.electrical_design.inverter_instances;
  // Inverter sections: open by default for one or two inverters, closed from three up (F1.1).
  const [openInv, setOpenInv] = useForm<Record<string, boolean>>("elec.open", {});
  const startOpen = inverters.length <= 2;
  const isOpen = (id: string) => openInv[id] ?? startOpen;
  const setAll = (open: boolean) => setOpenInv(Object.fromEntries(inverters.map((i) => [i.inverter_instance_id, open])));
  const allOpen = inverters.every((i) => isOpen(i.inverter_instance_id));

  return (
    <>
      <Section primary title={t("systems.inverters")}>
        <ComponentFilterBar items={v.catalog.inverters} filter={invFilter} onChange={setInvFilter} showTest={showTest} />
        <div className="grid2">
          <Field label="Model">
            <Select
              value={addable.some((i) => i.revision_id === add.def) ? add.def : addable[0]?.revision_id ?? ""}
              onChange={(def) => setAdd({ ...add, def })}
              options={addable.map((i) => ({ value: i.revision_id, label: componentCatalogLabel(i, `${i.model} · ${i.mppt_count} MPPT`, t("s12a.librarySuffix"), t("s12a.layoutOnlySuffix")) }))}
            />
          </Field>
          <Field label="Name">
            <input className="input" value={add.name} onChange={(e) => setAdd({ ...add, name: e.target.value })} />
          </Field>
        </div>
        <Button
          small
          disabled={!!state.busy}
          onClick={async () => {
            const def = addable.some((i) => i.revision_id === add.def) ? add.def : addable[0]?.revision_id ?? "";
            const r = await engineCommand("Adding inverter", () => engine.addInverter(pid, { inverter_definition_revision_id: def, name: add.name }));
            if (r) {
              // The new inverter opens; from three inverters up the others fold away.
              const before = new Set(inverters.map((i) => i.inverter_instance_id));
              const next = r.bundle.electrical_design.inverter_instances;
              setOpenInv(Object.fromEntries(next.map((i) => [i.inverter_instance_id, !before.has(i.inverter_instance_id) || (next.length <= 2 && isOpen(i.inverter_instance_id))])));
            }
          }}
        >
          Add inverter
        </Button>
        <Check checked={showTest} onChange={setShowTest} label={t("use1.showTest")} />

      {inverters.length > 1 && (
        <div className="sectionbar">
          <span className="sub">{t("electrical.inverterCount", { count: inverters.length })}</span>
          <button type="button" className="linkbtn" onClick={() => setAll(!allOpen)} aria-expanded={allOpen}>
            {allOpen ? t("electrical.collapseAll") : t("electrical.expandAll")}
          </button>
        </div>
      )}

      {inverters.map((inv) => {
        const d = state.electrical[inv.inverter_instance_id];
        if (!d) return null;
        const def = v.catalog.inverters.find((i) => i.revision_id === inv.inverter_definition_revision_id);
        const mppts = v.topology_view.inverters.find((i) => i.inverter_instance_id === inv.inverter_instance_id)?.mppts ?? [];
        const statedInputs = Math.max(0, ...mppts.map((m) => m.input_count ?? 0)) || def?.inputs_per_mppt;
        const inputsSource = statedInputs ? (mppts.some((m) => m.input_count) ? t("str1.definitionSource") : t("str1.catalogSource", { source: def?.inputs_per_mppt_source })) : d.inputsSource;
        const buffer = buffers[inv.inverter_instance_id];
        const text = buffer ?? d.notation;
        const parsed = parseNotation(text);
        const setBuffer = (next: string | null) => {
          const b = { ...buffers };
          if (next === null || next === d.notation) delete b[inv.inverter_instance_id];
          else b[inv.inverter_instance_id] = next;
          setBuffers(b);
        };
        const available = d.pairedFieldIds.length ? d.pairedFieldIds.reduce((t, f) => t + (perField[f] ?? 0), 0) : null;
        const res = parsed.layout
          ? checkLayout({ layout: parsed.layout, mpptCount: def?.mppt_count ?? null, inputsPerMppt: d.inputsPerMppt, modulesAvailable: available, unequalParallelPolicy: "warning" })
          : null;
        const kwp = v.bundle.scene.module_instances.filter(m => d.pairedFieldIds.includes(m.pv_field_id)).reduce((total,m) => {
          const revision = modulePlacement(v, m.module_instance_id)?.revisionId;
          const definition = v.catalog.modules.find(x => x.revision_id === revision);
          return total + (definition ? moduleNameplateW(definition) : 0) / 1000;
        }, 0);
        const setD = (patch: Partial<typeof d>) => dispatch({ type: "setElectrical", inverterId: inv.inverter_instance_id, patch });
        const setLayout = (l: MpptLayout) => setBuffer(formatNotation(l));
        const width = Math.max(d.inputsPerMppt ?? 1, ...(parsed.layout?.mppts.map((m) => m.length) ?? [1]));
        const blocking = res?.issues.filter((x) => x.severity === "blocking").length ?? 0;
        const warnings = res?.issues.filter((x) => x.severity === "warning").length ?? 0;
        const topoInv = v.topology_view.inverters.find((t) => t.inverter_instance_id === inv.inverter_instance_id);
        // Notation diff: string lengths per MPPT, engine against the edit buffer.
        const engineLens = topoInv ? lengthsPerMppt(layoutOfInverter(topoInv)) : [];
        const bufferLens = buffer !== undefined && parsed.layout ? lengthsPerMppt(parsed.layout) : null;
        const diff = bufferLens
          ? Array.from({ length: Math.max(engineLens.length, bufferLens.length) }, (_, i) => ({ i, from: (engineLens[i] ?? []).join(",") || "0", to: (bufferLens[i] ?? []).join(",") || "0" })).filter((x) => x.from !== x.to)
          : [];

        // Orientation per MPPT from the fields its current strings draw from.
        const mpptOrientation = (idx: number) => {
          const mppt = topoInv?.mppts[idx];
          if (!mppt) return null;
          const placements = mppt.strings.flatMap(s => v.bundle.electrical_design.strings.find(x => x.string_id === s.string_id)?.module_instance_ids ?? []).flatMap(id => {
            const p = modulePlacement(v, id); return p ? [p] : [];
          });
          if (!placements.some(p => isExplicitField(p.field))) {
          const fields = new Set<string>();
          for (const s of mppt.strings) {
            const str = v.bundle.electrical_design.strings.find((x) => x.string_id === s.string_id);
            for (const mid of str?.module_instance_ids ?? []) {
              const mi = v.bundle.scene.module_instances.find((x) => x.module_instance_id === mid);
              if (mi) fields.add(mi.pv_field_id);
            }
          }
          const fl = [...fields].map((id) => v.bundle.scene.pv_fields.find((x) => x.pv_field_id === id)).filter((field): field is NonNullable<typeof field> => !!field).filter(isGeneratedField);
          if (!fl.length) return null;
          let spread = 0;
          for (const a of fl) for (const b of fl) spread = Math.max(spread, normalAngleDeg(a.tilt_deg, a.azimuth_deg, b.tilt_deg, b.azimuth_deg));
          return { spread, label: fl.length === 1 ? `${fl[0].tilt_deg}° / ${fl[0].azimuth_deg}°` : `${fl.length} orientations` };
          }
          const orientations = [...new Map(placements.map(p => [`${p.tiltDeg}|${p.azimuthDeg}`, p])).values()];
          if (!orientations.length) return null;
          let spread = 0;
          for (const a of orientations) for (const b of orientations) spread = Math.max(spread, normalAngleDeg(a.tiltDeg, a.azimuthDeg, b.tiltDeg, b.azimuthDeg));
          return {spread, label: orientations.length === 1 ? `${orientations[0].tiltDeg}° / ${orientations[0].azimuthDeg}°` : `${orientations.length} orientations`};
        };

        return (
          <Section
            key={inv.inverter_instance_id}
            title={`${inv.name} · ${def?.model ?? inv.inverter_definition_revision_id}`}
            open={isOpen(inv.inverter_instance_id)}
            onOpenChange={(o) => setOpenInv({ ...openInv, [inv.inverter_instance_id]: o })}
            summary={
              <>
                <span>
                  {t("electrical.summary", {
                    mppt: def?.mppt_count ?? "?",
                    kwp: fmt(kwp, 2, "kWp"),
                    notation: d.notation.trim() || t("electrical.noNotation")
                  })}
                </span>
                {blocking > 0 && (
                  <span className="count count--blocked">
                    <GlyphBlocked />
                    {t("status.blocking", { count: blocking })}
                  </span>
                )}
                {warnings > 0 && (
                  <span className="count count--warning">
                    <GlyphWarning />
                    {t("status.warnings", { count: warnings })}
                  </span>
                )}
              </>
            }
          >
            <div className="statline">
              <span>{fmt((def?.nominal_ac_power_w ?? 0) / 1000, 0, "kW AC")}</span>
              <span>{def?.mppt_count ?? "?"} MPPT</span>
              <span>{fmt(kwp, 2, "kWp paired")}</span>
              <span>DC/AC {def && kwp ? (kwp / (def.nominal_ac_power_w / 1000)).toFixed(2) : "—"}</span>
            </div>
            <InverterLifecycle inv={inv} def={def} />

            <Field label="Paired PV fields">
              <div className="chips">
                {v.bundle.scene.pv_fields.map((fl) => {
                  const on = d.pairedFieldIds.includes(fl.pv_field_id);
                  return (
                    <button
                      key={fl.pv_field_id}
                      type="button"
                      className={on ? "chip chip--on" : "chip"}
                      aria-pressed={on}
                      disabled={!!state.busy}
                      onClick={() => topo({ command_type: "set_inverter_pairing", parameters: { inverter_instance_id: inv.inverter_instance_id, pv_field_ids: on ? d.pairedFieldIds.filter((x) => x !== fl.pv_field_id) : [...d.pairedFieldIds, fl.pv_field_id] } }, t("electrical.pairing"))}
                    >
                      {fl.name} <span className="count">{perField[fl.pv_field_id] ?? 0}</span>
                    </button>
                  );
                })}
              </div>
              <p className="sub">{d.pairedFieldIds.length ? t("electrical.pairingNote") : t("electrical.pairingNone")}</p>
            </Field>

            <div className="grid2">
              <Field label={t("str1.inputsLabel")} hint={statedInputs ? inputsSource : t("str1.inputsMissing")}>
                {statedInputs ? <input className="input input--num" type="number" value={statedInputs} readOnly /> : <NumberInput value={d.inputsPerMppt ?? 0} step={1} min={1} onChange={(n) => setD({ inputsPerMppt: n > 0 ? n : null })} />}
              </Field>
              <Field label={t("str1.sourceLabel")}>
                <input className="input" value={inputsSource} readOnly={!!statedInputs} placeholder="e.g. datasheet rev. 2024-03, p. 2" onChange={(e) => setD({ inputsSource: e.target.value })} />
              </Field>
            </div>

            <SuggestStringing inv={inv} pairedFieldIds={d.pairedFieldIds} onLayout={(layout, replace) => {
              setLayout(layout);
              setRestring((x) => ({ ...x, [inv.inverter_instance_id]: { text: formatNotation(layout), replace } }));
            }} />
            <Field label="MPPT layout" hint={t("electrical.notationHint")}>
              <input
                className={parsed.layout ? "input input--notation" : "input input--notation input--bad"}
                value={text}
                onChange={(e) => setBuffer(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Escape") setBuffer(null);
                }}
                spellCheck={false}
              />
            </Field>
            {buffer !== undefined && (
              <div className="notation-diff" role="status">
                <span className="tag tag--draft">{t("electrical.notationDraft")}</span>
                {diff.length ? (
                  <ul>
                    {diff.map((x) => (
                      <li key={x.i}>
                        MPPT {x.i + 1}: <code>{x.from}</code> → <code>{x.to}</code>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <span className="sub"> {t("electrical.notationSameLengths")}</span>
                )}
              </div>
            )}
            {parsed.layout && (
              <div className="statline statline--quiet">
                <span>{parsed.layout.mppts.length} MPPT groups</span>
                <span>{stringCount(parsed.layout)} strings</span>
                <span>{totalModules(parsed.layout)} modules</span>
              </div>
            )}
            {parsed.issues
              .filter((i) => i.severity === "blocking")
              .map((i) => (
                <div className="issue issue--blocking" key={i.message}>
                  {i.message}
                </div>
              ))}

            {parsed.layout && (
              <table className="tbl mppt-grid">
                <thead>
                  <tr>
                    <th>MPPT</th>
                    {Array.from({ length: width }, (_, i) => (
                      <th key={i} className="num">
                        In {i + 1}
                      </th>
                    ))}
                    <th>Orientation</th>
                    <th>Override</th>
                  </tr>
                </thead>
                <tbody>
                  {parsed.layout.mppts.map((row, r) => {
                    const o = mpptOrientation(r);
                    const mpptId = topoInv?.mppts[r]?.mppt_instance_id;
                    const saved = overrideOf(mpptId);
                    const on = !!mpptId && (saved !== null || !!overrideOpen[mpptId]);
                    const reason = mpptId ? reasonDraft[mpptId] ?? saved ?? "" : "";
                    const commitReason = () => {
                      if (!mpptId) return;
                      const text = reason.trim();
                      setReasonDraft((x) => { const n = { ...x }; delete n[mpptId]; return n; });
                      if (text && text !== saved) void topo({ command_type: "set_orientation_override", parameters: { mppt_instance_id: mpptId, reason: text } }, t("electrical.overriding"));
                    };
                    const mixed = o ? o.spread > tol : false;
                    return (
                      <tr key={r} className={res?.issues.some((i) => i.mppt === r && i.severity !== "info") ? "row--warn" : ""}>
                        <td>{r + 1}</td>
                        {Array.from({ length: width }, (_, c) => (
                          <td key={c} className="num">
                            <input
                              className="cell"
                              type="number"
                              aria-label={`MPPT ${r + 1}, input ${c + 1}, modules`}
                              min={0}
                              value={row[c] ?? 0}
                              onChange={(e) => {
                                const l = parsed.layout!.mppts.map((m) => [...m, ...Array(Math.max(0, width - m.length)).fill(0)]);
                                l[r][c] = Math.max(0, Math.trunc(Number(e.target.value) || 0));
                                setLayout({ mppts: l });
                              }}
                            />
                          </td>
                        ))}
                        <td>
                          {o ? (
                            <span className={mixed ? "orient orient--mixed" : "orient"}>
                              <StatusDot state={mixed ? (saved !== null ? "warn" : "fail") : "pass"} /> {o.label}
                              {o.spread >= 0.05 && ` · Δ${o.spread.toFixed(1)}°`}
                            </span>
                          ) : (
                            <span className="sub">no strings yet</span>
                          )}
                        </td>
                        <td>
                          <Check
                            checked={on}
                            disabled={!mpptId || !!state.busy}
                            onChange={(next) => {
                              if (!mpptId) return;
                              setOverrideOpen((x) => ({ ...x, [mpptId]: next }));
                              if (!next && saved !== null) void topo({ command_type: "set_orientation_override", parameters: { mppt_instance_id: mpptId, reason: null } }, t("electrical.overriding"));
                            }}
                            label={<span className="visually-hidden">{`Override orientation rule for MPPT ${r + 1}`}</span>}
                          />
                          {on && (
                            <input
                              className="input input--inline"
                              placeholder="Reason (required)"
                              aria-label={`Override reason for MPPT ${r + 1}`}
                              maxLength={500}
                              value={reason}
                              onChange={(e) => mpptId && setReasonDraft((x) => ({ ...x, [mpptId]: e.target.value }))}
                              onBlur={commitReason}
                              onKeyDown={(e) => { if (e.key === "Enter") commitReason(); }}
                            />
                          )}
                          {mixed && saved !== null && <span className="sub"> {t("electrical.overrideRunBlocked")}</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}

            {buffer !== undefined && <EngineDraftChecks inverterId={inv.inverter_instance_id} layout={parsed.layout} pairedFieldIds={d.pairedFieldIds} text={text}
              replace={restring[inv.inverter_instance_id]?.text === text ? restring[inv.inverter_instance_id].replace : []} />}
            {res && (
              <ul className="checklist">
                {res.checks.map((c) => (
                  <li key={c.id}>
                    <StatusDot state={c.state} />
                    <span className="checklist__label">{c.label}</span>
                    <span className="checklist__detail">{c.detail}</span>
                  </li>
                ))}
              </ul>
            )}

            <div className="row">
              <Button
                small
                tone="primary"
                disabled={!!state.busy || buffer === undefined || !parsed.layout || blocking > 0}
                onClick={async () => {
                  if (!parsed.layout) return;
                  const suggested = restring[inv.inverter_instance_id];
                  const layout = parsed.layout.mppts;
                  const r = suggested?.replace.length && suggested.text === text
                    ? await engineCommand(t("electrical.applyingLayout"), () => engine.applyLayoutReplacing(pid, inv.inverter_instance_id, layout, d.pairedFieldIds, suggested.replace))
                    // As the check above and the Systems table: the inverter's strings that the new layout does not keep release their modules.
                    : await topo({ command_type: "apply_mppt_layout", parameters: { inverter_instance_id: inv.inverter_instance_id, layout, pv_field_ids: d.pairedFieldIds, release_modules: true } }, t("electrical.applyingLayout"));
                  if (r) {
                    setBuffer(null);
                    setRestring((x) => { const n = { ...x }; delete n[inv.inverter_instance_id]; return n; });
                  }
                }}
              >
                {t("electrical.applyLayout")}
              </Button>
              <Button small disabled={buffer === undefined} onClick={() => setBuffer(null)}>
                {t("electrical.discard")}
              </Button>
              <Button
                small
                onClick={() => topo({ command_type: "assign_strings", parameters: { inverter_instance_id: inv.inverter_instance_id, string_ids: null } }, t("electrical.assigning"))}
                disabled={!!state.busy || v.topology_view.unassigned_strings.length === 0}
              >
                Assign unassigned ({v.topology_view.unassigned_strings.length})
              </Button>
            </div>
          </Section>
        );
      })}

      </Section>

      <Section primary title={t("sections.strings")}>
        <div className="toolrow" role="toolbar" aria-label={t("electrical.toolsTitle")}>
          {ELECTRICAL_TOOLS.map((d) => (
            <button
              key={d.tool}
              type="button"
              disabled={!!state.busy && d.tool !== "select" && d.tool !== "lasso"}
              className={state.tool === d.tool ? "btn btn--sm btn--on" : "btn btn--sm"}
              aria-pressed={state.tool === d.tool}
              title={t(d.note)}
              onClick={() => dispatch({ type: "setTool", tool: d.tool })}
            >
              {t(d.label)} <kbd>{d.key.toUpperCase()}</kbd>
              {!DEMO && d.pending && <NotWired id={d.pending} compact />}
            </button>
          ))}
        </div>
        <p className="sub" aria-live="polite">
          {target ? t("electrical.targetIs", { inverter: target.inv, mppt: target.m.index }) : t("electrical.noTarget")}
        </p>

        <TopologyTree />
        {v.topology_checks && <p className="sub">{t("checks.basis", { basis: v.topology_checks.basis })}</p>}
      </Section>

      <Section primary={state.selection.length > 0} title={t("electrical.selectionTitle")}>
        {selModules.length ? (
          <>
            <p className="sub">{t("electrical.selectionSummary", { modules: selModules.length, unstrung: unstrungSel.length, strings: selStrings.length })}</p>
            <div className="row wrap">
              <Button
                small
                disabled={!!state.busy || !unstrungSel.length}
                onClick={() =>
                  topo(
                    { command_type: "create_strings", parameters: { string_length: uni.len, module_instance_ids: unstrungSel, ordering: uni.ordering, allow_shorter_remainder: uni.remainder } },
                    t("electrical.creatingStrings")
                  )
                }
              >
                {t("electrical.stringSelection", { len: uni.len })}
              </Button>
              <Button
                small
                disabled={!!state.busy || !selStrings.length || !state.target}
                onClick={() => topo({ command_type: "assign_strings_to_mppt", parameters: { string_ids: selStrings, mppt_instance_id: state.target! } }, t("electrical.assigning"))}
              >
                {t("electrical.assignToTarget")}
              </Button>
              <Button small disabled={!!state.busy || !selStrings.length} onClick={() => topo({ command_type: "unassign_strings", parameters: { string_ids: selStrings } }, t("electrical.unassigning"))}>
                {t("electrical.unassign")}
              </Button>
              <Button small disabled={!!state.busy || !selStrings.length} onClick={() => topo({ command_type: "delete_strings", parameters: { string_ids: selStrings } }, t("electrical.deleting"))}>
                {t("electrical.deleteStrings")}
              </Button>
              <Button small disabled={!!state.busy || !selTable} title={selTable ? undefined : t("electrical.replicateNeedsTable")} onClick={() => topo({ command_type: "replicate_pattern", parameters: { source_pv_field_id: selTable!.field, source_table_id: selTable!.table } }, t("electrical.replicating"))}>
                {t("electrical.replicate")}
              </Button>
            </div>
            <p className="sub">{selTable ? t("electrical.replicateNote", { table: selTable.table }) : t("electrical.replicateNeedsTable")}</p>
          </>
        ) : (
          <p className="sub">{t("electrical.selectionEmpty")}</p>
        )}
      </Section>

      <Section title={t("sections.rules")}>
        <div className="grid2">
          <Field label="Same-orientation tolerance" unit="°" hint={t("electrical.toleranceHint")}>
            <div onBlur={commitTol} onKeyDown={(e) => { if (e.key === "Enter") commitTol(); }} data-orientation-tolerance>
              <NumberInput value={tolDraft ?? engineTol} step={0.1} min={0} max={1} disabled={!!state.busy} onChange={setTolDraft} />
            </div>
          </Field>
          <Field label="Default">
            <input className="input" value="1 MPPT = 1 orientation" readOnly />
          </Field>
        </div>

        <div className="grid2">
          <Field label={t("electrical.modulesPerString")}>
            <NumberInput value={uni.len} step={1} min={1} onChange={(len) => setUni({ ...uni, len })} />
          </Field>
          <Field label={t("electrical.pvField")}>
            <Select value={uni.field} onChange={(field) => setUni({ ...uni, field })} options={[{ value: "", label: t("electrical.allUnstrung") }, ...v.bundle.scene.pv_fields.map((f) => ({ value: f.pv_field_id, label: f.name }))]} />
          </Field>
        </div>
        <FieldGroup label={t("electrical.ordering")} hint={t("electrical.orderingHint")}>
          <Segmented<StringOrdering>
            label={t("electrical.ordering")}
            value={uni.ordering === "selection" ? "row_major" : uni.ordering}
            onChange={(ordering) => setUni({ ...uni, ordering })}
            options={[
              { value: "row_major", label: t("electrical.rowMajor") },
              { value: "serpentine", label: t("electrical.serpentine") }
            ]}
          />
        </FieldGroup>
        <Check checked={uni.remainder} onChange={(remainder) => setUni({ ...uni, remainder })} label={t("electrical.allowRemainder")} />
        <div className="row">
          <Button
            small
            disabled={!!state.busy}
            onClick={() =>
              topo(
                { command_type: "create_strings", parameters: { string_length: uni.len, pv_field_id: uni.field || null, ordering: uni.ordering === "selection" ? "row_major" : uni.ordering, allow_shorter_remainder: uni.remainder } },
                t("electrical.creatingStrings")
              )
            }
          >
            {t("electrical.createStrings")}
          </Button>
        </div>
      </Section>
    </>
  );
}
