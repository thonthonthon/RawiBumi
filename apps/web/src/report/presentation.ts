export const INSTALLATION_TYPES = ["on_grid", "on_grid_zero_export", "off_grid", "hybrid"] as const;
export type InstallationType = (typeof INSTALLATION_TYPES)[number];

export interface SystemInfo {
  installationType: InstallationType | null;
  /** Usable energy capacity, kWh. Null: not given. 0: no battery. */
  bessEnergyKwh: number | null;
  /** Rated power, kW. Optional. */
  bessPowerKw: number | null;
}

export const EMPTY_SYSTEM: SystemInfo = { installationType: null, bessEnergyKwh: null, bessPowerKw: null };

/** True when the cover states something the simulation does not model. */
export function beyondSimulation(s: SystemInfo): boolean {
  return (s.installationType !== null && s.installationType !== "on_grid") || (s.bessEnergyKwh ?? 0) > 0 || (s.bessPowerKw ?? 0) > 0;
}

const fmt = (x: number, digits: number) => x.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** PV capacity: kWp below 1,000 kWp (1 decimal), MWp from 1,000 kWp (2 decimals). */
export function formatPvCapacity(kwp: number): string {
  return kwp >= 1000 ? `${fmt(kwp / 1000, 2)} MWp` : `${fmt(kwp, 1)} kWp`;
}

/** Energy: kWh below 1,000 kWh (up to 1 decimal), MWh from 1,000 kWh (2 decimals). */
export function formatEnergy(kwh: number): string {
  return kwh >= 1000 ? `${fmt(kwh / 1000, 2)} MWh` : `${kwh.toLocaleString("en-US", { maximumFractionDigits: 1 })} kWh`;
}

/** Power: kW below 1,000 kW, MW from 1,000 kW. */
export function formatPower(kw: number): string {
  return kw >= 1000 ? `${fmt(kw / 1000, 2)} MW` : `${kw.toLocaleString("en-US", { maximumFractionDigits: 1 })} kW`;
}

