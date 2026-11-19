# Decision 0006 — Canonical weather uses explicit intervals and energy-preserving resolution conversion

**Status:** Accepted for v0.1 implementation  
**Date:** 2026-09-23

## Decision

OpenSIMPV canonical weather timestamps represent interval starts.

Every dataset records both source-native resolution and current series resolution.

Source timestamp conventions are normalized explicitly and recorded as transformations.

## Irradiance

Canonical irradiance values are interval-average fluxes in W/m2.

Where source files store one-hour irradiation energy in Wh/m2, the value is converted to the
corresponding one-hour interval-average W/m2 and the conversion is recorded.

## Sub-hourly weather

Phase-2 disaggregation uses deterministic interval-mean hold.

This creates synthetic child intervals but exactly preserves source irradiance energy.

The synthetic resolution must never be described as the native measurement resolution.

A more physical clear-sky-normalized shaping method may be added later as a separate named
model after solar geometry exists.

## Quality control

QC must not repair or fill weather silently.

Detected gaps, invalid values, missing components, or physically suspicious values are
reported as structured findings.

Solar-geometry-dependent QC is deferred until the solar-position engine exists.

## PVsyst compatibility

OpenSIMPV supports the documented PVsyst Standard weather CSV interchange format.

The internal .MET object serialization is not guessed because PVsyst treats that file
structure as an internal implementation format rather than a stable external schema.

Direct internal .MET support may be added later only against a verified redistributable
fixture and explicit field semantics.

## Consequences

- weather provenance survives timestep conversion;
- a one-minute simulation can distinguish native one-minute weather from synthetic
  one-minute weather derived from hourly input;
- timestamp errors cannot be hidden by implicit midpoint/end conventions;
- Phase 3 can apply solar position at interval midpoint without changing weather storage
  semantics;
- later disaggregation algorithms can coexist without changing historical run meaning.
