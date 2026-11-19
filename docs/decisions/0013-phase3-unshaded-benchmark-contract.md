# Decision 0013 — Phase 3 unshaded validation uses separate native-resolution and PVsyst reference families

**Status:** Accepted for Phase 3.0  
**Date:** 2026-09-23

## Context

Phase 3 introduces the first complete unshaded numerical simulation chain. Validation must
separate three different temporal questions:

1. native hourly weather evaluated hourly;
2. native subhourly/minute weather evaluated at its native cadence;
3. OpenSIMPV-generated subhourly weather derived from hourly input.

The available reference material contains two different Meteonorm generations:

- standalone Meteonorm 8.2 DAT exports at 60, 15, 10, and 1 minute;
- PVsyst V8.1.6 reports using integrated Meteonorm 9.0 weather, with legacy hourly and
  modern native one-minute simulation variants.

The two Meteonorm generations are not numerically interchangeable. Their annual GHI differs
materially, so comparing OpenSIMPV against PVsyst must not silently substitute the standalone
Meteonorm 8.2 files for PVsyst's Meteonorm 9 weather.

## Decision

Phase 3 uses three benchmark families defined in
`tests/benchmarks/phase3_unshaded.yaml`.

### Family A — WX-MN82-NATIVE

Native Meteonorm 8.2 standalone weather:

- 3600 s;
- 900 s;
- 600 s;
- 60 s.

These cases validate native-resolution weather/timeline behavior and later POA, thermal, DC,
and AC sensitivity to temporal resolution.

The source files remain external user-supplied references and are not redistributed in the
repository. Their filenames, SHA-256 hashes, byte sizes, row counts, cadence, and annual
irradiance totals are frozen in the benchmark contract.

### Family B — SYS-PVSYST-V816-UNSHADED

Eight PVsyst V8.1.6 end-to-end cases:

- DC/AC 1.19: hourly and one-minute;
- DC/AC 1.39: hourly and one-minute;
- DC/AC 1.58: hourly and one-minute;
- DC/AC 1.78: hourly and one-minute.

All use the same module/inverter family, fixed orientation, no 3D scene, no near shading, and
explicitly reported thermal, IAM, wiring, module-quality, mismatch, inverter-conversion, and
clipping behavior.

The PVsyst variant name `NoLoss` is not interpreted as a mathematically lossless system.

The reference contract freezes annual and monthly energy outputs plus key irradiance and
inverter/clipping targets from the reports.

Hourly/minute PVsyst pair differences are treated as an end-to-end temporal-resolution and
weather-representation comparison, not as a pure numerical timestep delta.

### Family C — WX-OSPV-DERIVED

OpenSIMPV-derived subhourly cases start from the Meteonorm 8.2 hourly reference and target:

- 15 minutes;
- 10 minutes;
- 5 minutes;
- 1 minute.

These cases are explicitly `opensimpv_derived`, not native Meteonorm subhourly weather.

Required invariants include:

- source-interval irradiance-energy preservation;
- daylight-only irradiance shape;
- no artificial night irradiance;
- retained native-resolution provenance.

## Benchmark philosophy

External software agreement is evidence, not truth.

Phase 3 must compare intermediate stages rather than tune only to annual AC energy:

```text
weather
→ solar position
→ POA
→ effective irradiance
→ temperature
→ module DC
→ string / MPPT
→ inverter conversion
→ clipping
→ AC / PCC energy
```

A discrepancy should be localized to the earliest stage at which it appears.

## Source redistribution

Uploaded/reference weather files and PVsyst reports are not committed to the public
repository unless redistribution permission is established.

The repository stores only:

- source-identifying metadata;
- source hashes where locally available;
- extracted engineering reference targets;
- test invariants.

## Meteonorm signed-coordinate correction

The Meteonorm 8.2 Home files expose a parser edge case:

```text
-6.425 [deg N]
```

The explicit numeric sign is authoritative. The parser must not convert this to +6.425°
because of the N token.

Phase 3.0 therefore includes a narrow Meteonorm coordinate-parsing regression before the
benchmark family is considered usable.

## Consequences

- native minute weather is distinct from derived minute weather;
- legacy PVsyst hourly simulation remains an explicit compatibility track;
- modern PVsyst one-minute simulation is an optional high-resolution reference track;
- Meteonorm 8.2 and PVsyst/Meteonorm 9 references cannot be mixed silently;
- future Phase-3 PRs consume one stable machine-readable benchmark contract.
