import type { ExecutionReadiness, ProjectView } from "../types";

type Finding = ExecutionReadiness["findings"][number];

/** USE1 (E1): a readiness blocker the user can act on, in plain words; the raw rule stays alongside as evidence. */
export interface PlainFinding {
  key: string;
  values: Record<string, string | number>;
  rule_id: string;
  message: string;
  /** The inverter revision a "Complete from datasheet" or "Switch" action applies to. */
  inverterRevisionId?: string;
  inverterInstanceId?: string;
}

const INVERTER_DATA = new Set(["INVERTER_BASIC_DESIGN_READY_FALSE", "INVERTER_MPPT_DESIGN_READY_FALSE"]);

export function plainFindings(findings: readonly Finding[], view: ProjectView): PlainFinding[] {
  const inverters = view.bundle.electrical_design.inverter_instances;
  const mpptOwner = new Map(inverters.flatMap((i) => i.mppt_instance_ids.map((m) => [m, i.inverter_instance_id] as const)));
  const name = (id?: string | null) => inverters.find((i) => i.inverter_instance_id === id)?.name ?? id ?? "";
  const out: PlainFinding[] = [];
  const seen = new Set<string>();
  for (const f of findings) {
    const id = f.entity_id ?? undefined;
    const inverter = inverters.find((i) => i.inverter_instance_id === id);
    if (INVERTER_DATA.has(f.rule_id) && inverter) {
      if (seen.has(`data:${id}`)) continue;
      seen.add(`data:${id}`);
      out.push({ key: "use1.plain.inverterData", values: { name: inverter.name }, rule_id: f.rule_id, message: f.message,
        inverterRevisionId: inverter.inverter_definition_revision_id, inverterInstanceId: inverter.inverter_instance_id });
    } else if (f.rule_id === "SIMULATION_INVERTER_HAS_NO_SIMULATED_STRINGS") {
      out.push({ key: "use1.plain.noStrings", values: { name: name(id) }, rule_id: f.rule_id, message: f.message });
    } else if (f.rule_id === "EXECUTION_WEATHER_REVISION_REQUIRED" || f.rule_id === "weather.missing") {
      out.push({ key: "use1.plain.noWeather", values: {}, rule_id: f.rule_id, message: f.message });
    } else if (f.rule_id === "MPPT_SHORT_CIRCUIT_CURRENT_EXCEEDED") {
      out.push({ key: "use1.plain.isc", values: { name: name(mpptOwner.get(id ?? "")) }, rule_id: f.rule_id, message: f.message });
    } else {
      out.push({ key: "", values: {}, rule_id: f.rule_id, message: f.message });
    }
  }
  return out;
}
