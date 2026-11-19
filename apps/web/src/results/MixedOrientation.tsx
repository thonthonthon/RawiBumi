import { useTranslation } from "react-i18next";
import type { ProjectBundle, SimulationRunRecord } from "../types";
import { fmt } from "../ui/kit";

type Mixed = NonNullable<SimulationRunRecord["mixed_orientation"]>;
type Diagnostics = Pick<Mixed["mppts"][number], "multi_peak_duration_hours" | "energy_gaps_wh">;

/** Recorded diagnostics only: neither a tracker penalty nor an estimate for missing periods. */
export function MixedOrientationResults({ run, bundle }: { run: SimulationRunRecord; bundle: ProjectBundle }) {
  const { t } = useTranslation();
  const mixed = run.mixed_orientation;
  if (!mixed) return null;
  const period = mixed.period_totals;
  const moduleName = (revision: string) => bundle.pinned_components?.modules[revision]?.model ?? t("s15.notRecorded");
  const inverterName = (id: string) => bundle.electrical_design.inverter_instances.find(inv => inv.inverter_instance_id === id)?.name ?? t("s15.notRecorded");
  const mpptIndex = (inverterId: string, mpptId: string) => bundle.electrical_design.mppt_instances
    ?.find(mppt => mppt.inverter_instance_id === inverterId && mppt.mppt_instance_id === mpptId)?.index ?? t("s15.notRecorded");
  const cells = (row: Diagnostics) => <>
    <td data-multi-peak-hours={row.multi_peak_duration_hours}>{fmt(row.multi_peak_duration_hours, 3)}</td>
    {(["simple_tracker", "second_highest", "lowest"] as const).map(key =>
      <td key={key} data-tracker-gap={key} data-gap-wh={row.energy_gaps_wh[key]}>−{fmt(row.energy_gaps_wh[key]/1000, 3)} kWh</td>)}
  </>;
  return <>
    <div className="issue issue--draft" role="status" data-mixed-orientation-result>
      <strong>{t("use5b.banner")}</strong>
      {Object.entries(mixed.bypass_basis_by_module_revision).map(([revision, basis]) => basis &&
        <p key={revision} data-bypass-revision={revision}>
          {basis.no_bypass_current_limited ? <>{t("use5b.bypassData")} · {t("use5b.noBypass")} · {moduleName(revision)}</>
            : basis.count_basis === "data" && basis.forward_voltage_basis === "data"
              ? <>{t("use5b.bypassData")} · {moduleName(revision)} ({basis.diode_count} × {basis.forward_voltage_v} V)</>
              : <>{t(basis.count_basis === basis.forward_voltage_basis ? "use5b.bypassAssumed" : "use5b.bypassBasis", { count: basis.diode_count, voltage: basis.forward_voltage_v, module: moduleName(revision) })}
                {basis.count_basis !== basis.forward_voltage_basis && <> · {t("use5b.countBasis", { basis: t(`use5b.${basis.count_basis}`) })}; {t("use5b.voltageBasis", { basis: t(`use5b.${basis.forward_voltage_basis}`) })}</>}</>}
        </p>)}
      <p>{t("use5b.tracker")}</p>
    </div>
    <section className="panel-card" aria-label={t("use5b.diagnostics")} data-mixed-diagnostics>
      <h3>{t("use5b.diagnostics")}</h3>
      <p>{t("use5b.lowerPeak")}</p>
      <p className="note">{t("use5b.diagnosticNote")}</p>
      <p data-mixed-coverage={mixed.is_complete_year ? "annual" : "partial"}>
        {mixed.is_complete_year ? t("use5b.annual") : t("use5b.partial", {
          start: period.start_time, end: period.end_time, hours: period.duration_hours })}
      </p>
      <table className="tbl">
        <thead><tr><th>MPPT</th><th>{t("use5b.multiPeakHours")}</th>
          <th>{t("use5b.simpleTracker")}</th><th>{t("use5b.secondHighest")}</th><th>{t("use5b.lowest")}</th></tr></thead>
        <tbody>
          <tr data-mixed-total><th scope="row">{t("use5b.plant")}</th>{cells(period)}</tr>
          {mixed.mppts.map(row => <tr key={`${row.inverter_instance_id}/${row.mppt_instance_id}`} data-mixed-mppt={row.mppt_instance_id} data-mixed-inverter={row.inverter_instance_id}>
            <th scope="row">{inverterName(row.inverter_instance_id)} / MPPT {mpptIndex(row.inverter_instance_id, row.mppt_instance_id)}</th>{cells(row)}
          </tr>)}
        </tbody>
      </table>
      <p>{t("use5b.mpptHours", { hours: period.multi_peak_mppt_duration_hours })}</p>
    </section>
  </>;
}
