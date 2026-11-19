
# ADR 0043 — Direct-beam shading uses polygon projection as the Phase-5 reference kernel

**Status:** Accepted by Phase 5.3  
**Date:** 2026-09-24

## Context

Phase 5.0 froze shading conventions. Phase 5.1 produced deterministic compiled receiver/occluder geometry. Phase 5.2 established receiver-aware simulation execution groups.

The next requirement is a correct direct-beam geometry solver.

A general ray engine, BVH, or GPU implementation would introduce optimization and numerical complexity before a reference answer exists. Overlapping projected geometry must also be unioned rather than summed.

## Decision

1. Implement Phase-5.3 direct-beam shading by parallel polygon projection onto the receiver plane.
2. Use the frozen receiver-to-sun vector and project opposite that vector.
3. Clip every occluder face to the receiver sunward half-space before projection.
4. Convert projected geometry to a deterministic local receiver-plane basis.
5. Clip each projected polygon to the receiver polygon.
6. Union all resulting shadow polygons before measuring shaded area.
7. Use pinned Shapely 2.1.2 / GEOS as the reference planar topology engine.
8. Record Shapely and GEOS runtime versions in every query result.
9. Keep numerical tolerances explicit and solver-version-bound.
10. Exclude the receiver's own source entity unconditionally.
11. Apply other-module occlusion only when self_shading_enabled is true.
12. Respect shading_enabled for all compiled occluders.
13. Treat sun-below-horizon and receiver-backside cases as neutral geometric modifiers with explicit statuses.
14. Fail closed on nonplanar receivers, missing geometry provenance, unsupported mesh geometry, and materially invalid projected polygons.
15. Do not add spatial acceleration in Phase 5.3.
16. Do not integrate the kernel into annual SimulationRun in Phase 5.3.

## Consequences

Positive:

- direct-beam geometry has a small, inspectable reference implementation;
- analytical cases can be tested exactly;
- overlapping shadows cannot exceed receiver area through double counting;
- tilted and rotated receiver geometry uses the same algorithm;
- self-shading behavior is explicit;
- future optimized or ray solvers have a reference oracle;
- numerical differences can be tied to solver and GEOS versions.

Deliberate limitations:

- polygon-face geometry only;
- no arbitrary mesh execution;
- no spatial acceleration;
- one receiver and one sun vector per query;
- no diffuse or ground obstruction;
- no annual integration;
- no electrical mismatch.

## Revisit condition

A future solver may replace or supplement polygon projection only after it reproduces the Phase-5.3 analytical matrix and is benchmarked against this reference kernel within an explicit tolerance.
