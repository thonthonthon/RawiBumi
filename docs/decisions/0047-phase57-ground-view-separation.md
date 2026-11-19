# ADR 0047 — Separate uniform-ground receiver visibility from ground illumination

**Status:** Accepted by Phase 5.7  
**Date:** 2026-09-24

## Context

The current front-side transposition model already produces a scalar-albedo ground-reflected POA component.

Geometry can affect that channel in at least two materially different ways:

1. receiver-side obstruction of the reflected lower hemisphere;
2. spatial shadowing of the ground irradiance source before reflection.

Implementing both simultaneously would silently introduce a spatial ground-radiance model that the current transposition contract does not contain.

The existing Phase-5.3 beam API also contains a correct solar-specific rule that treats global z <= 0 as no direct sunlight, so it cannot be reused unchanged for ground source directions.

## Decision

1. Phase 5.7 models receiver-side obstruction of the existing uniform Lambertian scalar-albedo ground-reflected POA only.
2. Spatial ground-illumination shadow maps are deferred.
3. Introduce a generic source-direction finite-receiver visibility kernel with no global solar-horizon rule.
4. Preserve the existing direct-beam public API and all Phase-5.3 horizon/status semantics unchanged.
5. Ground uses a deterministic global lower-hemisphere dome.
6. Lower-hemisphere bands are uniform in sin(depression).
7. Ground patches are weighted by solid angle multiplied by positive receiver cosine response.
8. A receiver with zero projected front-side lower-hemisphere view receives neutral ground visibility 1 because its conventional ground POA source term is zero.
9. Use the existing ground_visibility_factor channel.
10. Keep numerical albedo and geometric ground visibility separate.
11. Scale only the ground-reflected POA channel in the Phase-5.7 modifier.
12. Preserve beam and all Phase-5.6 sky components exactly.
13. Require ground-dome resolution explicitly in ShadingConfiguration.
14. Compute receiver ground visibility once per receiver set per run.
15. Area-weight receiver ground factors only at the existing homogeneous electrical boundary and record the approximation.
16. Preserve receiver-level ground factors for later electrical and irradiance models.
17. Do not infer support Surface objects as ground occluders or reflecting source meshes.

## Consequences

Positive:

- the three front-side geometry channels remain physically separable;
- the direct-beam solar horizon rule remains intact;
- lower-hemisphere geometry gains an explicit reusable directional kernel;
- albedo remains auditable as an input rather than being absorbed into a fitted shading factor;
- ground visibility has analytical view-factor references;
- later spatial ground or bifacial models can supersede the source model without changing the visibility convention.

Deliberate limitations:

- uniform Lambertian ground source;
- no spatial ground illumination;
- no spatial albedo;
- no bifacial rear irradiance;
- finite dome resolution;
- homogeneous electrical group aggregation;
- no electrical mismatch.

## Revisit condition

A future spatial ground-irradiance or bifacial model may replace the uniform source assumption and consume directional or spatial receiver visibility at higher fidelity. It should not collapse albedo and geometry into one coefficient, and it must preserve the Phase-5.3 beam wrapper semantics.
