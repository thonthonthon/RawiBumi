import { useStore } from "../state/store";
import { Paid } from "../ui/kit";

/** Simple SLD (free): strings → MPPT → inverter → PCC/grid with load. No equipment ratings. */
export function Sld() {
  const { state } = useStore();
  const v = state.view!;
  const invs = v.topology_view.inverters;
  const rowH = 30;
  const blocks = invs.map((inv) => ({ inv, rows: Math.max(1, inv.mppts.length) }));
  const H = Math.max(200, blocks.reduce((t, b) => t + b.rows * rowH + 40, 90));
  const W = 780;
  let y = 30;
  const busX = 590;
  const invYs: number[] = [];
  return (
    <div className="sld">
      <div className="sld__head">
        <strong>Single-line diagram</strong>
        <span className="sub">Simple (free): topology only, no ratings. Full SLD with combiners, LVMDP, transformer and ratings</span> <Paid what="Full SLD" />
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="sld__svg" role="img" aria-label="Single-line diagram">
        {blocks.map(({ inv, rows }) => {
          const top = y;
          const invY = top + (rows * rowH) / 2;
          invYs.push(invY);
          y += rows * rowH + 40;
          return (
            <g key={inv.inverter_instance_id}>
              {inv.mppts.map((m, i) => {
                const my = top + i * rowH + rowH / 2;
                const label = m.strings.length ? m.strings.map((s) => `${s.name}·${s.module_count}`).join("  ") : "unused";
                return (
                  <g key={m.mppt_instance_id}>
                    <rect x={30} y={my - 10} width={200} height={20} className={m.strings.length ? "sld__pv" : "sld__pv sld__pv--empty"} />
                    <text x={40} y={my} dominantBaseline="middle" className="sld__txt">
                      {label}
                    </text>
                    <line x1={230} x2={300} y1={my} y2={my} className="sld__wire" />
                    <text x={306} y={my} dominantBaseline="middle" className="sld__small">
                      MPPT {m.index}
                    </text>
                    <line x1={356} x2={410} y1={my} y2={invY} className="sld__wire" />
                  </g>
                );
              })}
              <text x={440} y={invY - 30} textAnchor="middle" className="sld__txt sld__txt--b">
                {inv.name}
              </text>
              <rect x={410} y={invY - 20} width={60} height={40} className="sld__inv" />
              <path d={`M 410 ${invY + 20} L 470 ${invY - 20}`} className="sld__wire" />
              <text x={418} y={invY - 8} className="sld__small">=</text>
              <text x={456} y={invY + 14} className="sld__small">~</text>
              <line x1={470} x2={busX} y1={invY} y2={invY} className="sld__wire" />
            </g>
          );
        })}
        {invYs.length > 0 &&
          (() => {
            const top = Math.min(...invYs) - 10;
            const pccY = Math.min(...invYs);
            const loadY = Math.max(...invYs) + 50;
            return (
              <>
                <line x1={busX} x2={busX} y1={top} y2={loadY + 4} className="sld__bus" />
                <line x1={busX} x2={660} y1={pccY} y2={pccY} className="sld__wire" />
                <circle cx={675} cy={pccY} r={15} className="sld__node" />
                <text x={675} y={pccY} textAnchor="middle" dominantBaseline="middle" className="sld__small">
                  PCC
                </text>
                <line x1={690} x2={730} y1={pccY} y2={pccY} className="sld__wire" />
                <text x={736} y={pccY} dominantBaseline="middle" className="sld__txt">
                  Grid
                </text>
                <line x1={busX} x2={busX + 50} y1={loadY} y2={loadY} className="sld__wire" />
                <path d={`M ${busX + 50} ${loadY - 8} l 16 8 l -16 8 z`} className="sld__load" />
                <text x={busX + 74} y={loadY} dominantBaseline="middle" className="sld__txt">
                  Load
                </text>
              </>
            );
          })()}
      </svg>
    </div>
  );
}
