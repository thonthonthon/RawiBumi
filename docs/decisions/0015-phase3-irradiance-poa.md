# Decision 0015 — Phase 3.2 completes irradiance explicitly and preserves POA components

**Status:** Accepted for Phase 3.2  
**Date:** 2026-09-23

## Context

The weather foundation may supply:

- complete GHI/DNI/DHI;
- one missing direct/diffuse component;
- partial gaps in DNI/DHI;
- GHI-only intervals.

Phase 2.1 identifies the affected intervals but intentionally does not generate irradiance.

Phase 3 must complete only what is missing, avoid unstable direct-normal derivation near the
horizon, and keep transposition inspectable for later optical and shading stages.

## Decision

### Component completion hierarchy

OpenSIMPV uses this order:

1. preserve valid source DNI/DHI exactly;
2. derive one missing component analytically from the horizontal identity where stable;
3. apply explicit low-sun protection;
4. use a named decomposition model only for still-unresolved daytime intervals.

The horizontal identity is:

```text
GHI = DNI · cos(zenith) + DHI
```

DNI derivation is not performed when the cosine of zenith falls below the configured
threshold or zenith exceeds the configured limit.

At low sun:

```text
missing DNI → 0

if DNI and DHI are both missing:
    DNI = 0
    DHI = GHI
```

Materially negative irradiance produced by analytical completion is an error rather than
being silently clipped. Small numerical negatives within the explicit tolerance may be
floored to zero.

### Decomposition models

Supported named models are:

```text
irradiance.decomposition.erbs.pvlib.v0.1
irradiance.decomposition.disc.pvlib.v0.1
irradiance.decomposition.dirint.pvlib.v0.1
```

All use the true solar zenith because the corresponding pvlib decomposition APIs define that
input as non-refraction-corrected zenith.

DIRINT uses time-series context and, where complete, canonical weather pressure and dew-point
temperature.

No decomposition model is selected implicitly.

### POA transposition

Supported named models are:

```text
poa.transposition.isotropic.pvlib.v0.1
poa.transposition.haydavies.pvlib.v0.1
poa.transposition.perez.pvlib.v0.1
poa.transposition.perez_driesse.pvlib.v0.1
```

POA uses apparent zenith and the canonical compass azimuth convention.

The engine preserves:

```text
POA beam
POA sky diffuse
POA ground diffuse
POA total diffuse
POA global
```

and requires exact numerical reconciliation:

```text
POA global
    =
POA beam
+ POA sky diffuse
+ POA ground diffuse
```

For anisotropic models, sky diffuse is further exposed as:

```text
isotropic
circumsolar
horizon
```

when supported by pvlib 0.15.2. This is retained because later IAM handling may treat
circumsolar irradiance differently from isotropic/horizon diffuse.

### Perez configuration

The classic Perez wrapper records the coefficient set explicitly. The initial default
coefficient-set argument is `allsitescomposite1990`, but the transposition **model itself**
is still mandatory and is not globally frozen as the OpenSIMPV default.

Perez-Driesse remains available as a modern continuous alternative.

### Unshaded boundary

Phase 3.2 applies no horizon or near shading:

```text
beam factor    = 1
diffuse factor = 1
ground factor  = 1
```

The shading engine will connect only after the unshaded numerical chain is stable.

## Validation

Analytical regressions cover:

- direct/diffuse horizontal identity;
- low-sun behavior;
- source-value preservation;
- horizontal-plane POA identity;
- direct beam at normal incidence;
- closed-form isotropic sky/ground diffuse terms;
- diffuse-subcomponent reconciliation for Hay-Davies, Perez, and Perez-Driesse.

The Phase-3 external Meteonorm/PVsyst families remain higher-level validation targets and are
not used to tune these equations.

## Consequences

- later engine stages know exactly which irradiance values were source, analytical, or
  modeled;
- low-sun DNI cannot explode numerically;
- POA discrepancies can be localized to beam, sky, ground, or diffuse subcomponents;
- Phase 3.3 can apply component-aware IAM without reconstructing Perez circumsolar energy.
