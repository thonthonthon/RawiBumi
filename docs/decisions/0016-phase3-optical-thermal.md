# Decision 0016 — Phase 3.3 uses component-aware tabulated IAM and explicit PVsyst thermal inputs

**Status:** Accepted for Phase 3.3  
**Date:** 2026-09-23

## Context

Phase 3.2 preserves direct beam, isotropic diffuse, circumsolar diffuse, horizon diffuse, and
ground-reflected POA separately.

The Phase-3 PVsyst reference module contains:

```text
Absorb = 0.90

IAMMode = UserProfile
IAMProfile = TCubicProfile
0°   1.000
30°  1.000
50°  1.000
60°  0.999
70°  0.988
75°  0.965
80°  0.925
85°  0.743
90°  0.000
```

The PVsyst reports configure:

```text
Uc = 20 W/m²K
Uv = 0 W/m²K/(m/s)
```

A transparent optical/thermal engine must preserve these source semantics without replacing
them with unnamed generic defaults.

## Decision

### IAM models

Phase 3.3 supports:

```text
iam.none.v0.1
iam.tabulated.pvlib_interp.v0.1
```

The tabulated model requires explicit:

- reference AOI values;
- reference IAM values;
- interpolation method;
- normalization policy.

The PVsyst benchmark uses cubic interpolation because the PAN source declares
`TCubicProfile`.

AOI at or behind 90° is assigned zero direct IAM.

### Component treatment

Direct beam and circumsolar diffuse use the IAM evaluated at the solar AOI.

The remaining diffuse classes use solid-angle integrated factors derived from the same IAM
curve with Marion's numerical method as implemented by
`pvlib.iam.marion_integrate`:

```text
isotropic sky → sky diffuse IAM
horizon       → horizon IAM
ground        → ground IAM
```

No hidden diffuse IAM constants are introduced.

The effective irradiance ledger preserves:

```text
effective beam
effective isotropic
effective circumsolar
effective horizon
effective sky diffuse
effective ground diffuse
effective total diffuse
effective global
```

and requires exact component reconciliation.

### Thermal model

The supported Phase-3 thermal model is:

```text
thermal.pvsyst.pvlib.v0.1
```

with:

```text
Tc = Ta + alpha * E * (1 - eta_m) / (Uc + Uv * WS)
```

implemented by `pvlib.temperature.pvsyst_cell`.

The irradiance basis is incident POA global **before IAM**. Optical reflection is represented
by the absorption coefficient, not by substituting IAM-reduced effective irradiance into the
heat balance.

`Uc`, `Uv`, absorption coefficient, and module efficiency are explicit.

When `Uv=0`, wind speed is mathematically irrelevant and may be absent. When `Uv!=0`,
complete wind input is required.

### Module efficiency boundary

The reference PAN gives:

```text
width  = 1.134 m
height = 2.278 m
PNom   = 550 W
```

therefore:

```text
area = 2.583252 m²
STC efficiency = 550 / (1000 * 2.583252)
               = 0.2129099290351851
```

This STC value is frozen in the benchmark contract as reference data.

However, the PVsyst thermal equation defines `eta_m` as operating external module
efficiency. Phase 3.3 therefore does not silently use STC efficiency for integrated annual
simulation. Phase 3.4 will provide interval electrical efficiency and later orchestration may
iterate temperature/electrical state as required.

## Validation

Analytical regressions cover:

- reproduction of the PVsyst IAM control points;
- unity-IAM diffuse integration;
- deterministic sky/horizon/ground diffuse factors;
- beam/circumsolar component-aware IAM application;
- optical component reconciliation;
- exact PVsyst thermal closed-form temperature;
- `Uv=0` wind-independence;
- non-zero `Uv` wind requirement;
- zero-POA ambient-temperature behavior;
- PAN-derived area/STC-efficiency/absorption reference consistency.

## Consequences

- `GlobInc → GlobEff` can later be diagnosed by optical component rather than one aggregate
  loss number;
- the PVsyst user IAM profile remains traceable to the source PAN;
- thermal parity is not obtained by an undocumented efficiency assumption;
- Phase 3.4 can connect detailed module electrical output to the existing thermal equation.
