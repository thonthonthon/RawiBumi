# ADR 0042 — Simulation execution groups replace project-wide irradiance flattening

**Status:** Accepted by Phase 5.2  
**Date:** 2026-09-24

## Context

The Phase-3 numerical worker accepts one homogeneous fixed-tilt configuration.

Before Phase 5.2, canonical topology resolution enforced that worker limitation
too early by requiring one project-wide module revision, string length,
orientation and albedo.

Phase 4 and Phase 5 canonical design models are spatially richer than that
backend assumption.

A geometry-aware engine therefore needs a derived layer that preserves distinct
irradiance states without prematurely claiming detailed electrical mismatch
support.

## Decision

1. Introduce `SimulationExecutionGroupPlan` as derived execution state.
2. Group strings by common inverter, module revision, string length,
   orientation and resolved albedo.
3. Do not include MPPT identity in the group signature.
4. Retain MPPT membership separately.
5. Strings with identical state across multiple MPPTs may remain one group.
6. Different groups on separate MPPTs are classified as
   `separable_multi_group`.
7. Different groups sharing one MPPT are classified as
   `electrically_coupled_heterogeneous`.
8. One string spanning multiple states is invalid and is not split.
9. Link the plan to Phase-5.1 compiled receiver geometry where available.
10. Preserve existing homogeneous numerical behavior by adapting exactly one
    valid execution group back into the legacy worker.
11. Record execution-plan identity in run reproducibility metadata.
12. Do not implement detailed same-MPPT electrical interaction in Phase 5.2.

## Consequences

### Positive

- project-wide one-orientation flattening is removed from canonical topology;
- multi-orientation designs can be represented faithfully before execution;
- MPPT-separable geometry is distinguished from electrically coupled mismatch;
- future beam shading can attach to stable receiver/module groups;
- the legacy numerical worker remains unchanged for existing supported cases;
- Phase-6 electrical boundaries are explicit.

### Deliberate limitations

- the current backend still executes only one homogeneous group;
- separable multi-group execution remains a later Phase-5 integration task;
- same-MPPT heterogeneous groups remain blocked;
- multiple inverter execution remains outside the current worker scope.
