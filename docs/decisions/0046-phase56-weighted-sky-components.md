# ADR 0046 — Weighted global sky dome with separate circumsolar and horizon obstruction

**Status:** Accepted by Phase 5.6  
**Date:** 2026-09-24

## Context

OpenSIMPV already exposes diffuse POA as isotropic, circumsolar, and horizon subcomponents, and its IAM layer treats those components differently.

A single generic sky obstruction factor would erase this distinction and would not represent Perez-family diffuse behavior defensibly.

## Decision

1. Use a deterministic global upper-sky dome for isotropic sky obstruction.
2. Discretize elevation uniformly in mu = sin(elevation), giving equal-solid-angle bands.
3. Weight every patch by patch solid angle multiplied by positive receiver cosine response.
4. Reuse the Phase-5.3 full-polygon directional visibility kernel for every sampled sky direction.
5. Use a separately configured low-elevation dome for the horizon component.
6. Use the current sun-direction beam visibility as circumsolar directional visibility.
7. Keep isotropic, circumsolar, and horizon irradiance channels separate through near-shading reconstruction.
8. Apply diffuse geometry after POA transposition and before IAM.
9. Preserve the Phase-5.5 direct-beam result unchanged.
10. Preserve ground-reflected POA unchanged until Phase 5.7.
11. Treat Perez horizon as a potentially signed empirical correction and scale the signed term linearly.
12. Require the sky/horizon dome resolution explicitly in SimulationConfiguration; do not derive it invisibly from fidelity_level.
13. Compute static isotropic/horizon visibility once per receiver set per run.
14. Area-weight module receiver factors only at the existing homogeneous electrical execution boundary and disclose that approximation.
15. Preserve receiver-level sky/circumsolar/horizon factors for later higher-fidelity electrical models.
16. Keep historical pvsyst_shd_reference configurations as external-oracle references, not internal solver aliases.

## Consequences

Positive:

- diffuse geometry follows the existing transposition decomposition;
- isotropic and directional diffuse are no longer conflated;
- sky integration has a clear mathematical weighting basis;
- circumsolar obstruction shares the already validated sun-direction geometry;
- horizon visibility has independent resolution and provenance;
- Phase-5.5 beam regression remains directly testable;
- ground obstruction remains a distinct later channel;
- receiver spatial factors survive for Phase 6.

Deliberate limitations:

- finite sky-dome resolution is a numerical approximation;
- horizon-band representation is a model approximation to the empirical transposition horizon term;
- receiver factors are area-weighted to one homogeneous electrical state;
- no electrical mismatch physics is claimed;
- no persistent sky cache or acceleration structure is introduced;
- arbitrary imported mesh support remains outside the compiled geometry boundary.

## Revisit condition

The component geometry contract should remain stable when acceleration is added. A future higher-fidelity electrical solver may consume receiver-level component irradiance directly and supersede only the group-level aggregation approximation, not the sky geometry factors themselves.
