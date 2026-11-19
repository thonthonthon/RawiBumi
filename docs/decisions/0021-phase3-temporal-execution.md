# Decision 0021 — Phase 3.8 separates native weather cadence from working simulation cadence

**Status:** Accepted for Phase 3.8  
**Date:** 2026-09-23

## Context

The simulation specification requires hourly and sub-hourly execution while keeping the
source weather resolution visible.

In particular:

- native weather resolution is not simulation resolution;
- a one-minute simulation based on hourly weather is still based on hourly information;
- normal resolution conversion must preserve source-interval irradiance energy;
- interval energy uses explicit duration;
- the V1 target cadences are 60, 300, 900, and 3600 seconds;
- exact hourly-to-minute irradiance shaping remains an open v0.2 decision.

The Phase-3 reference corpus contains two distinct temporal evidence families:

1. standalone Meteonorm 8.2 weather at native 60/600/900/3600-second cadence;
2. PVsyst 8.1.6 end-to-end simulations using integrated Meteonorm 9 weather at
   native hourly and native one-minute cadence.

Those families are not numerically interchangeable.

## Decision

### One temporal execution boundary

Resolution conversion occurs once:

```text
canonical input weather
→ explicit temporal preparation
→ working weather
→ simulation timeline
→ all solar / irradiance / thermal / electrical physics
```

No downstream stage performs hidden resampling.

### Three cadence concepts remain separate

Phase 3.8 records:

```text
native_resolution_seconds
input_series_resolution_seconds
simulation_timestep_seconds
```

They are not aliases.

The native resolution always remains the resolution declared by the source importer.

The input-series resolution is the cadence of the canonical series supplied to the run.

The simulation timestep is the selected working cadence after any explicit resolution
conversion.

### Working-series origin remains explicit

The temporal context retains:

```text
native_series_origin
input_series_origin
working_series_origin
```

A series produced by OpenSIMPV resolution conversion is marked:

```text
working_series_origin = opensimpv_derived
```

It is never relabeled as measured or provider-native data.

### Provider-generated native subhourly weather is a distinct case

A provider-generated one-minute series can have:

```text
native_resolution_seconds = 60
native_series_origin = provider_generated
upstream_generation.base_resolution_seconds = 3600
```

This is not the same thing as OpenSIMPV taking an hourly file and disaggregating it to one
minute.

Phase 3.8 therefore reports:

```text
temporal_fidelity = provider_generated_native_subhourly
```

when that provenance is present.

### Interval-level temporal provenance

Every working interval records:

- input interval start and end;
- number of input intervals contributing to the working interval;
- native resolution;
- input-series resolution;
- working simulation resolution;
- relation to native cadence;
- relation to the current input series;
- whether OpenSIMPV disaggregation occurred;
- whether OpenSIMPV aggregation occurred;
- working-series origin.

This makes derived fine-resolution intervals inspectable rather than implied.

### V1 target cadences

The accepted V1 target set is:

```text
60 s
300 s
900 s
3600 s
```

The engine does not unnecessarily prohibit other positive timesteps. The current
resolution converter accepts other timesteps when the input/target ratio is an exact
integer and the coverage can be grouped without truncation.

### Current OpenSIMPV disaggregation model

The existing explicit baseline remains:

```text
algorithm = interval_mean_hold
algorithm_version = 0.1
```

For each coarse source interval, the interval-average meteorological values are held over
the child intervals.

For irradiance:

```text
sum(child interval energy) = source interval energy
```

within numerical tolerance.

This model is intentionally described as a **conservative low-fidelity baseline**.

The simulation specification prefers a future solar-geometry-informed intrainterval shape
normalized back to the source-interval energy. Because the exact shaping model is still an
open v0.2 decision, Phase 3.8 does not silently invent one.

Any simulation finer than the native source cadence therefore carries a false-precision
warning.

### Complete unshaded runner

Phase 3.8 adds one integrated fixed-tilt unshaded runner:

```text
temporal preparation
→ solar position
→ irradiance completion
→ POA
→ IAM
→ thermal/electrical fixed point
→ string
→ MPPT
→ explicit array losses
→ inverter
→ loss ledger
→ interval/monthly/annual energy
→ PV KPIs
```

All stages consume one common working interval index.

The runner requires explicit string-to-MPPT assignment and the validated component
definitions already established in earlier Phase-3 steps.

### Energy duration authority

Final energy integration uses:

```text
timeline.duration_seconds
```

not timestamp-spacing inference.

Therefore the last interval is not special or ambiguous.

### Cross-resolution validation

A synthetic diffuse-only horizontal reference is used as an end-to-end temporal invariant.

Because:

- DNI = 0;
- DHI = GHI;
- surface tilt = 0;
- IAM = identity;
- coarse values are interval-held;

the complete nonlinear electrical chain should integrate to the same energy at
60/300/900/3600-second execution.

This fixture validates execution semantics, not real subhourly irradiance variability.

### PVsyst oracle boundary

The supplied PVsyst oracle contains native:

```text
3600 s
60 s
```

cases only.

The standalone Meteonorm 8.2 10-minute and 15-minute files do not create 10-minute or
15-minute PVsyst reference simulations.

Likewise, the Meteonorm 8.2 location/weather family is not used as a numerical replacement
for the integrated Meteonorm 9 PVsyst weather family.

## Validation

Phase 3.8 regressions cover:

- native-cadence no-op execution;
- hourly-to-minute provenance and irradiance-energy preservation;
- provider-generated native-minute provenance;
- native-minute to 15-minute aggregation;
- rejection of non-integer cadence conversion;
- complete unshaded physics at 60/300/900/3600 seconds;
- end-to-end diffuse-horizontal energy invariance across those cadences;
- deterministic repeated execution;
- result manifest, KPI, duration, and provenance exposure;
- the frozen Phase-3 temporal benchmark contract.

## Consequences

- the complete Phase-3 unshaded pipeline is now cadence-agnostic;
- resolution conversion is visible and cannot occur silently inside physics stages;
- native one-minute data and synthetic one-minute data remain distinguishable;
- the current hourly-to-minute method preserves energy without claiming subhourly weather
  truth;
- Phase 3.9 can execute the hourly and native-minute PVsyst comparison through one common
  engine path;
- a future solar-geometry-informed disaggregation algorithm can replace or coexist with the
  v0.1 hold model under a new model/version identifier.
