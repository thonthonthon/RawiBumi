import { useStore } from "../state/store";
import { Button, fmt, Section } from "../ui/kit";

function Cap({ ok, label }: { ok: boolean | undefined; label: string }) {
  return <span className={ok ? "cap cap--ok" : "cap"}>{label}</span>;
}

export function ComponentsPanel({ onImport }: { onImport: () => void }) {
  const { state } = useStore();
  const c = state.view!.catalog;
  return (
    <>
      <Section title="Modules" aside={<Button small onClick={onImport}>Import PAN / template…</Button>}>
        <table className="tbl">
          <thead>
            <tr>
              <th>Model</th>
              <th className="num">Pmp</th>
              <th className="num">W × H (m)</th>
              <th>Capability</th>
            </tr>
          </thead>
          <tbody>
            {c.modules.map((m) => (
              <tr key={m.revision_id}>
                <td>
                  {m.manufacturer} {m.model}
                  {m.synthetic_reference && <span className="tag">synthetic</span>}
                </td>
                <td className="num">{m.pmp_w} W</td>
                <td className="num">
                  {m.width_m.toFixed(3)} × {m.height_m.toFixed(3)}
                </td>
                <td>
                  <Cap ok label="layout" /> <Cap ok={m.simulation_ready} label="yield" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      <Section title="Inverters" aside={<Button small onClick={onImport}>Import OND / template…</Button>}>
        <table className="tbl">
          <thead>
            <tr>
              <th>Model</th>
              <th className="num">AC</th>
              <th className="num">MPPT</th>
              <th>Capability</th>
            </tr>
          </thead>
          <tbody>
            {c.inverters.map((i) => (
              <tr key={i.revision_id}>
                <td>
                  {i.manufacturer} {i.model}
                  {i.synthetic_reference && <span className="tag">synthetic</span>}
                </td>
                <td className="num">{fmt(i.nominal_ac_power_w / 1000, 0, "kW")}</td>
                <td className="num">{i.mppt_count}</td>
                <td>
                  <Cap ok={i.simulation_ready} label={i.simulation_ready ? "executable" : "design only"} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="note">Inputs per MPPT, MPPT current limits and bifaciality are not in the catalog summary yet; missing values stay missing and are entered with a source where needed.</p>
      </Section>
    </>
  );
}
