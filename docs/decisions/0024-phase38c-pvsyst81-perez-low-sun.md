# ADR 0024 — Phase 3.8C PVsyst 8.1 Perez and low-sun compatibility

Status: accepted with an external coefficient-data blocker  
Date: 2026-09-23

## Context

PVsyst 8.1.0 changed Perez transposition behavior for sub-hourly simulation.

OpenSIMPV previously exposed:

```text
poa.transposition.perez.pvlib.v0.1
poa.transposition.perez_driesse.pvlib.v0.1
```

Both are valid OpenSIMPV model options, but neither is equivalent to the
PVsyst 8.1 sub-hourly Perez path.

PVsyst's current documentation states that:

1. hourly Perez remains based on the Perez-1990 formulation;
2. sub-hourly Perez uses a separate 48-coefficient set for each integer divisor
   of 60 minutes;
3. the sub-hourly coefficients were refitted on a quality-controlled minute
   dataset covering 113 sites;
4. the new sets are used from PVsyst 8.1.0 onward;
5. PVsyst applies a low-sun cutoff at `HSol < 2°`, setting beam-incidence and
   circumsolar-incidence components to zero.

The current public PVsyst help documents the coefficient structure, fitting
purpose, and timestep dependence, but does not publish the numeric production
tables.

An earlier EUPVSEC 2023 publication exposes one proof-of-concept 1-minute
48-coefficient table. PVsyst later states that the production coefficients were
refit on the larger 113-site dataset and that there is a separate set for each
supported sub-hourly timestep. The old one-minute publication is therefore
useful evidence about the methodology, but it is not sufficient evidence for
the PVsyst 8.1 production tables.

## Decision

### 1. Add a separate PVsyst 8.1 Perez model ID

The compatibility model is:

```text
poa.transposition.pvsyst81_perez.v0.1
```

Ordinary pvlib Perez remains:

```text
poa.transposition.perez.pvlib.v0.1
```

Perez-Driesse remains:

```text
poa.transposition.perez_driesse.pvlib.v0.1
```

The latter two must never be labeled as the PVsyst 8.1 compatibility path.

### 2. Hourly execution

For a 3600-second simulation, the compatibility model uses the Perez-1990
`allsitescomposite1990` basis.

The hourly path is executable without an external coefficient table.

### 3. Sub-hourly execution is timestep-bound

PVsyst documents a different production coefficient set for each integer divisor
of 60 minutes.

OpenSIMPV therefore requires an explicit:

```text
PerezCoefficientSet
```

containing:

```text
coefficient_set_id
timestep_seconds
coefficients[8][6]
source_reference
pvsyst81_production_verified
```

The coefficient columns are:

```text
F11 F12 F13 F21 F22 F23
```

for each of the eight Perez sky-clearness bins.

A coefficient table whose timestep differs from the simulation timestep is
rejected.

### 4. Fail closed when production coefficients are unavailable

For sub-hourly execution, if no coefficient table is supplied, OpenSIMPV raises
an explicit error.

The engine shall not silently substitute:

- Perez-1990 coefficients;
- Perez-Driesse;
- the EUPVSEC-2023 proof-of-concept one-minute table;
- interpolation between tables from other timesteps;
- fitted coefficients inferred only from annual or monthly PVsyst results.

This is an epistemic correctness requirement. A runnable approximation is not
automatically a compatibility model.

An unverified coefficient set may be executed only through an explicit diagnostic
override. Metadata then marks the result as:

```text
subhourly_coefficient_parity_status = unverified_explicit_table
```

Such a run cannot be used as evidence of exact PVsyst 8.1 parity.

### 5. Custom Perez execution is explicit

OpenSIMPV implements the discrete Perez-1990 equation directly when an explicit
coefficient table is provided:

```text
F1 = max(0, F11 + Delta*F12 + z*F13)
F2 =        F21 + Delta*F22 + z*F23
```

with the standard eight clearness bins.

The transposed sky-diffuse ledger remains separated into:

```text
isotropic
circumsolar
horizon
```

so low-sun handling and later IAM remain auditable.

### 6. PVsyst low-sun rule

PVsyst documents:

```text
HSol < 2 degrees:
    BeamInc = 0
    CircInc = 0
```

OpenSIMPV applies this rule only in the PVsyst-8.1 compatibility model.

The cutoff is strict:

```text
HSol = 2.000... degrees -> no cutoff
HSol < 2 degrees        -> cutoff
```

### 7. Solar-height basis

PVsyst defines HSol geometrically from its solar-position equations.

OpenSIMPV therefore uses:

```text
solar_elevation_deg = 90° - true solar zenith
```

for the 2° cutoff, rather than refraction-corrected apparent elevation.

This preserves the semantic distinction even though OpenSIMPV's underlying
solar-position implementation is NREL SPA rather than PVsyst's own simplified
solar geometry.

### 8. Component behavior below 2°

When the cutoff applies:

```text
beam          -> zero
circumsolar   -> zero
isotropic     -> preserved
horizon       -> preserved
ground        -> preserved
```

After the cutoff, OpenSIMPV recomputes:

```text
POA sky diffuse
POA diffuse
POA global
```

and requires the component ledger to reconcile.

### 9. Benchmark interpretation

The existing PVsyst 8.1.6 benchmark contains hourly and one-minute system results.

For hourly cases, the Phase 3.8C compatibility model is executable.

For one-minute cases, the exact PVsyst 8.1 production coefficient table is a
remaining external-data dependency. Until that table is obtained or independently
reconstructed from sufficiently rich PVsyst interval-level evidence:

```text
exact one-minute Perez coefficient parity = unresolved
```

This known difference must be separated in Phase 3.9 attribution rather than
mixed into an unexplained total-energy residual.

## Evidence

Primary PVsyst documentation:

- Perez transposition model:
  https://www.pvsyst.com/help/physical-models-used/irradiation-models/perez-transposition-model.html
- PVsyst 8.1.0 release notes:
  https://www.pvsyst.com/help/release-notes/index.html
- Solar geometry:
  https://www.pvsyst.com/help/physical-models-used/solar-geometry.html

Supporting PVsyst publication:

- Michele Oliosi, Bruno Wittmer, André Mermoud, Agnes Bridel-Bertomeu,
  "Accounting for sub-hourly irradiance fluctuations in hourly performance
  simulations", EUPVSEC 2023.

## Consequences

Positive:

- hourly PVsyst-8.1 Perez behavior has a distinct executable path;
- the documented 2° low-sun rule is no longer mixed with unrelated irradiance
  completion thresholds;
- sub-hourly coefficient provenance is explicit;
- the engine cannot silently produce a false PVsyst-compatibility claim;
- future verified coefficient tables can be installed without redesigning the
  transposition engine;
- Perez-Driesse remains available as an OpenSIMPV alternative without semantic
  confusion.

Limitation:

- exact sub-hourly PVsyst 8.1 coefficient parity remains blocked by unavailable
  public numeric production tables.

This limitation is external evidence/data availability, not a missing engine
execution mechanism.

## Regression requirements

The Phase 3.8C gate requires tests proving:

1. hourly PVsyst compatibility equals ordinary Perez-1990 above the cutoff;
2. `HSol < 2°` zeros beam and circumsolar components;
3. exactly `HSol = 2°` is not cut off;
4. the cutoff uses true rather than apparent solar elevation;
5. isotropic, horizon, and ground components remain available below the cutoff;
6. sub-hourly execution fails without an explicit coefficient set;
7. coefficient-set timestep must equal simulation timestep;
8. unsupported non-divisor timesteps are rejected;
9. unverified coefficient sets require an explicit diagnostic override;
10. diagnostic runs are marked as unverified rather than compatibility evidence;
11. a verified timestep-specific 8x6 table can execute through the same engine;
12. the complete runner records the POA compatibility metadata.
