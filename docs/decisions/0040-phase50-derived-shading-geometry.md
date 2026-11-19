# ADR 0040 — Phase 5 uses derived compiled shading geometry and geometry-only shading semantics

**Status:** Accepted by Phase-5.0 contract  
**Date:** 2026-09-24

## Context

Phase 4 established a canonical Scene, deterministic derived 3-D verification
geometry, and a simulation path that fails explicitly when shading or
multi-orientation execution is unsupported.

Phase 5 needs a physics-ready representation that can support polygon shadow
projection, sky/ground visibility and later arbitrary mesh acceleration without
turning numerical implementation details into editable engineering state.

There is also a critical modeling boundary: geometrically shaded module area is
not equivalent to electrical mismatch loss.

## Decision

1. The canonical `Scene` remains the sole authoritative engineering geometry.
2. Phase 5 introduces `CompiledShadingGeometry` as deterministic derived
   numerical state.
3. The compiled artifact is non-editable and must retain exact Scene
   revision/hash provenance.
4. Local shading coordinates are X East, Y North, Z Up in metres.
5. `sun_vector` points from receiver toward the sun.
6. Visibility factor is 1 for clear and 0 for blocked.
7. Beam, sky-diffuse and ground visibility are separate physical channels.
8. Geometry-aware execution must explicitly declare fidelity, resolution,
   solver versions and cache policy.
9. Existing Phase-4 shading configurations remain serializable for
   reproducibility.
10. A stricter Phase-5 contract gate is required before geometry-aware physics
    executes.
11. Phase-5 `ShadingResult` declares electrical shading as `not_modeled`.
12. Detailed electrical mismatch is deferred to Phase 6.
13. Existing Phase-4 runtime scope blockers remain in place until later Phase-5
    tranches provide a defensible replacement.

## Consequences

### Positive

- no second geometry authority is created;
- shading algorithms can change without changing engineering intent;
- polygon and future mesh solvers can share one receiver/occluder contract;
- annual results can expose geometry provenance and cache identity;
- electrical shading cannot be accidentally inferred from geometric area loss;
- old Phase-4 benchmark packages remain reproducible.

### Deliberate limitations

Phase 5.0 does not provide a Scene compiler or a shading solver.

The exact canonical hashing implementation for compiled geometry is finalized
with the Phase-5.1 compiler.

The electrical worker remains homogeneous until the Phase-5.2 execution-group
refactor.
