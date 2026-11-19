import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CompleteFromDatasheet, readinessLabelKey } from "../electrical/ComponentActions";
import { useStore } from "../state/store";
import type { CatalogInverter, CatalogModule } from "../types";
import { ComponentFilterBar, filterComponents, NO_FILTER } from "../ui/ComponentFilter";
import { Button, Check, fmt, Section, Segmented } from "../ui/kit";
import { useShowTestComponents } from "../ui/testComponents";

/** USE3: the library is browsed through filters; at most this many rows are listed. */
const LIBRARY_ROWS = 50;

function Readiness({ ready }: { ready: boolean | undefined }) {
  const { t } = useTranslation();
  return <span className={ready === false ? "cap" : "cap cap--ok"}>{t(readinessLabelKey({ simulation_ready: ready }))}</span>;
}

function ModuleRows({ items }: { items: CatalogModule[] }) {
  const { t } = useTranslation();
  return (
    <table className="tbl">
      <thead><tr><th>Model</th><th className="num">Pmp</th><th className="num">W × H (m)</th><th>Capability</th></tr></thead>
      <tbody>
        {items.map((m) => (
          <tr key={m.revision_id} data-module-row={m.revision_id}>
            <td>{m.manufacturer} {m.model}{m.synthetic_reference && <span className="tag">{t("use1.testTag")}</span>}</td>
            <td className="num">{m.pmp_w} W</td>
            <td className="num">{m.width_m.toFixed(3)} × {m.height_m.toFixed(3)}</td>
            <td><Readiness ready={m.simulation_ready} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function InverterRows({ items }: { items: CatalogInverter[] }) {
  const { t } = useTranslation();
  return (
    <table className="tbl">
      <thead><tr><th>Model</th><th className="num">AC</th><th className="num">MPPT</th><th className="num">{t("use1.inputsPerMppt")}</th><th>Capability</th></tr></thead>
      <tbody>
        {items.map((i) => (
          <tr key={i.revision_id} data-inverter-row={i.revision_id}>
            <td>
              {i.manufacturer} {i.model}
              {i.synthetic_reference && <span className="tag">{t("use1.testTag")}</span>}
              {i.superseded_by && <span className="tag">{t("use1.superseded")}</span>}
            </td>
            <td className="num">{fmt(i.nominal_ac_power_w / 1000, 0, "kW")}</td>
            <td className="num">{i.mppt_count}</td>
            <td className="num" title={i.inputs_per_mppt_source ?? undefined}>{i.inputs_per_mppt ?? "—"}</td>
            <td>
              <Readiness ready={i.simulation_ready} />{" "}
              {i.simulation_ready === false && !i.superseded_by && i.source === "library" && <CompleteFromDatasheet revisionId={i.revision_id} />}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ComponentsPanel({ onImport }: { onImport: () => void }) {
  const { t } = useTranslation();
  const { state } = useStore();
  const v = state.view!;
  const c = v.catalog;
  const [showTest, setShowTest] = useShowTestComponents();
  const [kind, setKind] = useState<"inverters" | "modules">("inverters");
  const [filter, setFilter] = useState(NO_FILTER);
  // "In this project": what the design pins, so its gaps can be completed here.
  const usedModules = new Set(v.bundle.scene.module_instances.map((m) => m.module_definition_revision_id));
  const usedInverters = new Set(v.bundle.electrical_design.inverter_instances.map((i) => i.inverter_definition_revision_id));
  const projectModules = c.modules.filter((m) => usedModules.has(m.revision_id));
  const projectInverters = c.inverters.filter((i) => usedInverters.has(i.revision_id));
  const library = (kind === "modules" ? filterComponents(c.modules, filter, showTest) : filterComponents(c.inverters, filter, showTest));
  const shown = library.slice(0, LIBRARY_ROWS);
  return (
    <>
      <Section primary title={t("use3.inProject")}>
        {!projectModules.length && !projectInverters.length && <p className="sub">{t("use3.noneUsed")}</p>}
        {!!projectModules.length && <ModuleRows items={projectModules} />}
        {!!projectInverters.length && <InverterRows items={projectInverters} />}
      </Section>
      <Section primary={!usedModules.size && !usedInverters.size} title={t("use3.library")} aside={<span className="row">
        <Button small onClick={onImport}>Import PAN / template…</Button>
        <Button small onClick={onImport}>Import OND / template…</Button>
      </span>}>
        <Segmented<"inverters" | "modules"> label={t("use3.type")} value={kind} onChange={(k) => { setKind(k); setFilter({ ...filter, brand: "" }); }}
          options={[{ value: "inverters", label: t("use3.inverters") }, { value: "modules", label: t("use3.modules") }]} />
        <ComponentFilterBar items={kind === "modules" ? c.modules : c.inverters} filter={filter} onChange={setFilter} showTest={showTest} withStatus />
        <div data-library-results={library.length}>
          {kind === "modules" ? <ModuleRows items={shown as CatalogModule[]} /> : <InverterRows items={shown as CatalogInverter[]} />}
        </div>
        <p className="sub">{library.length > LIBRARY_ROWS ? t("use3.more", { shown: LIBRARY_ROWS, total: library.length }) : t("use3.count", { count: library.length })}</p>
        <Check checked={showTest} onChange={setShowTest} label={t("use1.showTest")} />
      </Section>
    </>
  );
}
