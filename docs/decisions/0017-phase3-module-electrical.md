# Decision 0017 — Phase 3.4 uses the validated PVsyst single-diode model and fixed-point thermal coupling

**Status:** Accepted for Phase 3.4  
**Date:** 2026-09-23

## Context

Phase 3.3 produces:

```text
effective irradiance
incident POA
PVsyst thermal equation
```

but the PVsyst thermal equation requires external module efficiency:

```text
eta_m = DC power / (incident POA × module area)
```

At the same time, detailed module DC power depends on cell temperature. Therefore thermal
state and electrical state are coupled.

The component subsystem already validates PAN-derived PVsyst-v6 single-diode parameters.
Phase 3 must use that validated semantics rather than implement a second independent PAN
interpretation.

## Decision

### Detailed module model

The runtime model ID remains:

```text
module.pvsyst_singlediode.v6
```

The engine uses the same helper that component validation uses to call
`pvlib.pvsystem.calcparams_pvsyst`.

The resulting diode parameters are solved with `pvlib.pvsystem.singlediode`.
The default solver is explicitly:

```text
lambertw
```

Per-interval outputs are:

```text
Isc
Voc
Imp
Vmp
Pmp
```

with numerical/physical guards:

```text
Voc >= Vmp >= 0
Isc >= Imp >= 0
Pmp = Vmp × Imp
```

### Irradiance and efficiency bases

The electrical model receives:

```text
effective irradiance after IAM
```

External module efficiency for the thermal equation is:

```text
eta_external
    =
Pmp / (incident POA global × module area)
```

A second diagnostic efficiency is also retained:

```text
eta_effective
    =
Pmp / (effective irradiance × module area)
```

These are intentionally distinct.

### Dark intervals

Intervals at or below an explicit small effective-irradiance threshold are assigned:

```text
Isc = Voc = Imp = Vmp = Pmp = 0
eta = 0
```

This prevents unstable or meaningless dark-state calls to the single-diode solver.

### Thermal/electrical coupling

Phase 3.4 uses deterministic fixed-point iteration:

```text
eta_0
→ thermal(eta_0)
→ electrical(T_0)
→ eta_1
→ thermal(eta_1)
→ ...
```

Convergence requires both:

```text
max |T_n - T_(n-1)| <= temperature tolerance
max |eta_electrical - eta_input| <= efficiency tolerance
```

The reference Phase-3 contract freezes:

```text
initial eta = 0.0
temperature tolerance = 1e-4 °C
efficiency tolerance = 1e-8
max iterations = 25
relaxation factor = 1.0
```

The zero initial efficiency is purely a numerical starting iterate. It is not the final
thermal efficiency assumption.

After convergence, one final thermal/electrical evaluation is performed and the returned
fixed-point residual is checked again.

Failure to converge is an error.

### Validation boundary

Normal simulation should use a component model selected by the progressive model resolver.
The helper that extracts the detailed PVsyst parameter set requires
`validation.passed = true`.

The lower-level numerical function can accept a complete parameter dictionary directly for
diagnostic or regression use. That does not change the resolver's trust policy.

## Validation

Phase 3.4 adds regressions for:

- validated synthetic PAN parameter extraction;
- exact agreement with an existing validated 600 W/m², 50 °C off-STC anchor;
- manufacturer Jinko PAN STC reproduction within the existing 2% component gate;
- zero-irradiance zero-IV behavior;
- incident-POA versus effective-irradiance efficiency basis;
- thermal/electrical fixed-point convergence;
- rejection of an explicitly unvalidated detailed component model.

## Consequences

- Phase 3 now has a detailed per-module DC operating state;
- Phase 3.3 thermal efficiency is no longer a fixed approximation;
- temperature and module power can be solved self-consistently;
- Phase 3.5 can aggregate identical modules into strings and MPPT groups without re-solving
  module physics;
- electrical model semantics remain anchored to the same PAN validation implementation.
