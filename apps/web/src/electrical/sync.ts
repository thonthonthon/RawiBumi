import type { TopologyView } from "../types";
import { formatNotation, type MpptLayout } from "./notation";

type TopologyInverter = TopologyView["inverters"][number];

/**
 * The MPPT layout an inverter has in the engine's topology: per MPPT, the
 * lengths of its strings in string order, padded with 0 to the widest MPPT.
 * Notation sync (B6) reads it, so the notation always shows what the engine has.
 */
export function layoutOfInverter(inv: TopologyInverter): MpptLayout {
  const lens = inv.mppts.map((m) => m.strings.map((s) => s.module_count));
  // Padded to the widest MPPT, or to the stated DC inputs when the view carries them,
  // so an empty input reads as 0 instead of disappearing.
  const width = Math.max(1, ...lens.map((l) => l.length), ...inv.mppts.map((m) => m.input_count ?? 0));
  return { mppts: lens.map((l) => [...l, ...Array(width - l.length).fill(0)]) };
}

export const notationOfInverter = (inv: TopologyInverter): string => formatNotation(layoutOfInverter(inv));

/** String lengths per MPPT, ignoring empty inputs and input order: what must agree between notation and tree. */
export const lengthsPerMppt = (layout: MpptLayout): number[][] => layout.mppts.map((m) => m.filter((n) => n > 0).sort((a, b) => a - b));
